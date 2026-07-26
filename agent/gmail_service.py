import imaplib
import email
import email.utils
from email.header import decode_header, make_header
import json
import sqlite3
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

import io
import sys
from rich.console import Console

_utf8_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
console = Console(file=_utf8_out, highlight=False)

def _safe_log(msg: str) -> None:
    """Print to console, safe for Windows charmap encoding."""
    console.print(msg)

def _clean_header(header_val: str) -> str:
    if not header_val:
        return ""
    try:
        return str(make_header(decode_header(header_val))).strip()
    except Exception:
        return str(header_val).strip()

def _validate_ai_consistency(analysis: dict) -> dict:
    category = analysis.get("category", "Other")
    if category in ["Applied", "Review", "Interview", "Rejected"]:
        summary = str(analysis.get("summary", "")).lower()
        if any(k in summary for k in [
            "prescription", "refill", "medication", "doctor", "pharmacy", "clinic", "amitriptyline", 
            "dentist", "recept", "herhaalrecept", "apotheek", "huisarts", "tandarts", "ziekenhuis", 
            "bill", "invoice", "tax", "belasting", "gemeente", "municipality", "shipment", 
            "delivery", "order", "package", "pakket", "bestelling", "flight", "hotel", "booking", 
            "reservation", "security code", "login code", "verification code", "password reset"
        ]):
            if any(k in summary for k in ["security code", "login code", "verification code", "password reset"]):
                analysis["category"] = "Other"
            else:
                analysis["category"] = "Personal"
    return analysis

def _refine_email_analysis(subject: str, sender: str, recipient: str, body: str, is_outbound: bool, analysis: dict, from_llm: bool = True) -> dict:
    category = analysis.get("category", "Other")
    company = analysis.get("company_name")
    summary = analysis.get("summary", subject)
    
    text = f"{subject} {sender} {recipient} {body[:1000]}".lower()

    # 1. Expanded ATS & Person Name Ban List
    ats_names = {
        "greenhouse", "lever", "workday", "homerun", "recruitee", "dayforce", "hroffice", 
        "no-reply", "noreply", "hr account", "werken", "hr admin", "testgorilla", 
        "luna van der vos", "marieke altenburg", "maaike leemkuil", "ashby", 
        "smartrecruiters", "jobvite", "personio", "workable", "icims", "successfactors",
        "rutgers, gerwin", "jim goslinga", "mendon people", "pinpoint",
        "teamtailor", "starred", "our company", "the company", "our team", "the team",
        "complete the application", "g it", "kristienne ruiz", "messages-noreply",
        "donotreply", "support", "careers"
    }
    
    if company and (any(ats in company.lower() for ats in ats_names) or "omar abdulghani" in company.lower()):
        company = None

    # 2. Domain-to-Company & Subject Override Mapping
    domain_map = {
        "hetabc.nl": "Het ABC",
        "tool2match.nl": "Tool2Match",
        "amstelveen.nl": "Gemeente Amstelveen",
        "excellence.ag": "Excellence AG",
        "excellence.de": "Excellence AG",
        "thdv.nl": "Tot Heil des Volks",
        "samsung.com": "Samsung",
        "deptagency.com": "DEPT",
        "jaarbeurs.nl": "Jaarbeurs",
        "hunkemoller": "Hunkemöller",
        "axioncontinu.nl": "AxionContinu",
        "lvnl.nl": "Luchtverkeersleiding Nederland",
        "linkedin.com": "LinkedIn",
        "linkedin": "LinkedIn",
        "gtecombv": "GTE",
        "gte.com": "GTE"
    }
    
    target_email = recipient if is_outbound else sender
    for dom, canonical_comp in domain_map.items():
        if dom in target_email.lower() or dom in text:
            company = canonical_comp
            break

    if "hunkemöller" in text or "hunkemoller" in text or "hkm@myworkday" in target_email.lower():
        company = "Hunkemöller"

    # 3. Extract company from regex if still missing
    if not company and category in ["Applied", "Review", "Interview", "Rejected"]:
        for scan_text in [subject, body[:600]]:
            m_comp = re.search(r'\b(?:at|to|bij|with|voor|functie van [^.\n]+? bij|position of [^.\n]+? with|position of [^.\n]+? at|application to |application at |sollicitatie bij |sollicitatie naar de functie van [^.\n]+? bij )\s*([A-Z][A-Za-z0-9\s&\'\.-]{1,25}?)(?:\s*\.|,|\s+wij|\s+we|\s+en|\s+in|\s+om|\s+wat|\s+-|\s+\(|$|\n|®|™)', scan_text)
            if m_comp:
                cand = m_comp.group(1).replace('®', '').replace('™', '').strip()
                if cand and len(cand) > 1 and cand[0].isupper() and not any(ats in cand.lower() for ats in ats_names) and "omar abdulghani" not in cand.lower() and not cand.lower().startswith(("our ", "the ", "this ", "your ", "a ", "an ", "my ", "complete ")):
                    company = cand
                    break

    # 4. Fallback sender name extraction
    if not company:
        sender_clean = _clean_header(target_email)
        if "<" in sender_clean:
            name_part = sender_clean.split("<")[0].replace('"', '').strip()
            if name_part and not any(ats in name_part.lower() for ats in ats_names) and "omar abdulghani" not in name_part.lower():
                company = name_part.replace("Careers", "").replace("Talent", "").replace("Team", "").strip()

    # 5. Normalize canonical group name (strip departmental prefixes and legal suffixes)
    if company:
        company = re.sub(r'^(?:Info|No-Reply|Noreply|Support|Helpdesk|Contact|Service|Team|Recruitment|Careers|News|Newsletter|Orders|Billing|Admin|Office|Receptuur)\s+', '', company, flags=re.IGNORECASE).strip()
        company = re.sub(r'(\s+|,)+(?:Inc\.|Inc|B\.V\.|BV|LLC|Ltd\.|Ltd|GmbH|AG|Corp\.|Corp|Co\.|Co)$', '', company, flags=re.IGNORECASE).strip()
        if company == company.lower() and len(company) > 1:
            company = company.title()

    if category == "Interview":
        category = "Review"

    analysis["category"] = category
    analysis["company_name"] = company
    analysis["summary"] = summary
    return _validate_ai_consistency(analysis)


class GmailService:
    def __init__(self, workspace_path: str = "."):
        self.workspace_path = Path(workspace_path)
        self.db_path = self.workspace_path / "data" / "user_workspace" / "job_scout.db"
        load_dotenv(self.workspace_path / "data" / ".env")
        
        self.email_address = os.getenv("GMAIL_ADDRESS")
        self.app_password = os.getenv("GMAIL_APP_PASSWORD")
        
        # Load the centralized AI settings
        from agent.ai_settings_service import AISettingsService
        from agent.user_workspace import UserWorkspace
        workspace = UserWorkspace(self.workspace_path)
        ai_settings = AISettingsService(workspace).payload()
        
        self.providers_config = {p["id"]: p for p in ai_settings.get("providers", [])}
        backend_order_raw = ai_settings.get("backend_order", [])
        if isinstance(backend_order_raw, str):
            self.backend_order = [b.strip() for b in backend_order_raw.split(",") if b.strip()]
        else:
            self.backend_order = list(backend_order_raw)
        
        # Ensure lmstudio is at the end of the order as the ultimate fallback
        if "lmstudio" in self.backend_order:
            self.backend_order.remove("lmstudio")
        self.backend_order.append("lmstudio")

    def _connect_db(self):
        return sqlite3.connect(self.db_path)

    def repair_existing_emails(self, conn=None):
        close_conn = False
        if conn is None:
            conn = self._connect_db()
            close_conn = True
        try:
            rows = conn.execute("SELECT message_id, subject, sender, snippet, payload_json FROM emails").fetchall()
            updated = 0
            for msg_id, subject, sender, snippet, payload_str in rows:
                if not payload_str:
                    continue
                try:
                    data = json.loads(payload_str)
                    recipient = data.get("recipient", "")
                    analysis = data.get("analysis", {})
                    is_outbound = data.get("is_outbound", False)
                    
                    old_cat = analysis.get("category")
                    old_comp = analysis.get("company_name")
                    old_sum = analysis.get("summary")
                    
                    if old_cat == "Interview":
                        analysis["category"] = "Review"
                    
                    body_text = data.get("body", "") or snippet or ""
                    from_llm = analysis.get("_from_llm", False) or (old_sum and old_sum != subject and old_sum != "Email received.")
                    analysis = _refine_email_analysis(subject or "", sender or "", recipient or "", body_text, is_outbound, analysis, from_llm=from_llm)
                    new_cat = analysis.get("category", "Other")
                    new_comp = analysis.get("company_name")
                    new_sum = analysis.get("summary")
                    
                    data["analysis"] = analysis
                    
                    if old_cat != new_cat or old_comp != new_comp or old_sum != new_sum:
                        new_payload = json.dumps(data)
                        conn.execute("UPDATE emails SET category = ?, company_name = ?, payload_json = ? WHERE message_id = ?",
                                     (new_cat, new_comp, new_payload, msg_id))
                        updated += 1
                except Exception:
                    continue
            if updated > 0:
                conn.commit()
                _safe_log(f"Repaired {updated} email records in database.")
        except Exception as e:
            _safe_log(f"Error repairing email database: {e}")
        finally:
            if close_conn:
                conn.close()

    def _clean_html(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return text

    def _get_body(self, msg) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body += part.get_payload(decode=True).decode()
                    except Exception:
                        pass
                elif content_type == "text/html" and "attachment" not in content_disposition:
                    try:
                        html = part.get_payload(decode=True).decode()
                        body += self._clean_html(html)
                    except Exception:
                        pass
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True).decode()
                if content_type == "text/html":
                    body = self._clean_html(payload)
                else:
                    body = payload
            except Exception:
                pass
        return body

    def _truncate_text(self, text: str, max_words: int = 1500) -> str:
        words = text.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "\n...[TRUNCATED]"
        return text

    def _analyze_email_with_llm(
        self, subject: str, sender: str, recipient: str, cc: str, body: str, 
        is_outbound: bool = False, is_forwarded: bool = False, is_reply: bool = False, 
        is_automated: bool = False, has_attachments: bool = False, 
        has_calendar_invite: bool = False, thread_context: str = ""
    ) -> dict:
        # Keep prompt concise so local LLMs process it in < 2 seconds
        body_snippet = " ".join(body.split()[:300])
        
        direction_str = "OUTBOUND (Sent by you)" if is_outbound else "INBOUND (Received by you)"
        
        prompt = f"""Categorize this email. Translate internally and process emails in ANY language (Dutch, Spanish, etc.), but you MUST output the JSON summary and categories in ENGLISH.
Sender: {sender}
Recipient: {recipient}
Cc: {cc}
Subject: {subject}
Direction: {direction_str}
Is Forwarded: {is_forwarded}
Is Reply: {is_reply}
Is Automated Sender: {is_automated}
Has Attachments: {has_attachments}
Has Calendar Invite: {has_calendar_invite}
{f"Thread Context (Previous emails): {thread_context}" if thread_context else ""}
Body: {body_snippet}

Choose ONE category:
- Review: Active employer next steps, assessments, coding tests, take-home exercises, phone screens, interview invitations/confirmations, recruiter check-ins, or talent pool hold notices.
- Applied: Application confirmations, candidate portal access, account setups for job portals, Applicant Tracking System (ATS) notifications, or application submissions.
- Rejected: Job rejections.
- Promotions: Marketing, newsletters, sales.
- Personal: General non-job security alerts, non-job account notices, bills, or casual correspondence.
- Other: Anything else.

Rules for Categorization:
1. Self-Consistency Guardrail (HIGHEST PRECEDENCE): Your assigned category MUST be logically consistent with your summary. If your summary describes a doctor, prescription, medication, medical practice, bank account, tax notice, municipality, or casual personal correspondence, the category is STRICTLY FORBIDDEN from being 'Applied', 'Review', or 'Rejected'. It MUST be categorized as 'Personal' or 'Other'.
2. Thread State Progression:
   - For INBOUND Replies (from company to you): Read the new email carefully. If it is a rejection, classify as 'Rejected'. If it is an assessment, interview invite, or active review step, classify as 'Review'. Otherwise, maintain the current thread state (e.g. 'Applied').
   - For OUTBOUND Replies (from you to company): Inherit the job stage ONLY if the email is part of an active job application with a direct employer. Do NOT apply thread inheritance to personal, medical, or administrative emails.
3. OOO Exception: If an email is clearly an automated Out-of-Office (OOO) or vacation auto-reply, it MUST bypass thread inheritance and be categorized as 'Other'.
4. If Direction is OUTBOUND and it is a BRAND NEW email (no job-related Thread Context), categorize it as 'Personal' or 'Other', unless it's a clear outbound job application. Do NOT categorize casual emails to friends about jobs as 'Review' or 'Applied'.
5. Ensure your summary reflects the context (e.g. 'You confirmed your availability for the call' or 'Company placed your application on hold for future review').
6. ATS Override: Any emails sent from an ATS domain (e.g. workday, lever, greenhouse, homerun, myworkdayjobs) that are directly about a job application MUST be categorized as 'Applied' (or 'Review'/'Rejected' if applicable). Never categorize genuine job applications as 'Personal'.
7. Canonical Entity & Grouping (company_name): For EVERY email (whether job-related, personal, administrative, medical, or promotional), ALWAYS extract the clean, canonical organization or entity name that owns the conversation (e.g. 'Praktijk Bovenuit', 'DEPT', 'Tot Heil des Volks', 'Gemeente Amsterdam'). NEVER leave it null unless it is purely private correspondence between individuals with no organization. Strip all departmental prefixes (like 'Info', 'Noreply', 'Support', 'Helpdesk', 'Recruitment', 'Contact', 'Service') and legal suffixes (like BV, Inc, LLC). For example: 'Info Praktijk Bovenuit' -> 'Praktijk Bovenuit'. NEVER use software platform names (e.g. Greenhouse, Lever, Workday) as the group name. When replying or forwarding in a thread, inherit the exact same canonical entity name as the parent email to ensure they group together.
8. Smart Context (Outbound Updates): If an OUTBOUND email shares CVs, portfolio links, or application updates casually with an individual (e.g. a job coach, friend, gemeente, or caseworker), it MUST BE 'Personal'. Do NOT categorize as 'Applied' or 'Review' unless the email is an explicit application directly TO a company/HR.
9. Role Reversal Prevention: Always remember the 'Direction' of the email. If the Direction is OUTBOUND, the sender is YOU (the user) and the recipient is someone else. Do NOT confuse the pronouns 'I' and 'you' in the email body when writing your summary. For example, if you send an outbound email saying 'I have a phone screen', your summary should be 'You shared your schedule', NOT 'Inviting you to a phone screen'.

Return ONLY JSON format:
{{"category": "CategoryName", "company_name": "CompanyName or null", "job_title": "Job title if mentioned else null", "summary": "One extremely short, direct sentence (max 10 words)"}}
"""
        
        import time
        from agent.ai_settings_service import PROVIDERS
        
        provider_errors = []
        for backend_id in self.backend_order:
            provider = self.providers_config.get(backend_id)
            if not provider or (not provider.get("configured") and backend_id != "lmstudio"):
                continue
                
            model_name = provider.get("model")
            base_url = provider.get("base_url")
            key_env_var = PROVIDERS.get(backend_id, {}).get("key_env")
            api_key = os.getenv(key_env_var, "") if key_env_var else ""
            
            is_gemini = (backend_id == "gemini")
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            if api_key and not is_gemini:
                headers["Authorization"] = f"Bearer {api_key}"
            if backend_id == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/yourusername/job-hunt"
                headers["X-Title"] = "Job Hunt Agent"
                
            if is_gemini:
                req_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                payload = {
                    "systemInstruction": {"parts": [{"text": "You are a helpful assistant. Output ONLY valid JSON."}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512}
                }
            else:
                req_url = f"{base_url.rstrip('/')}/chat/completions"
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant. Output ONLY valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 512,
                    "temperature": 0.1
                }
                
            try:
                # Add 1.5s sleep for Cloud APIs to prevent rate limit
                if provider.get("hosted"):
                    time.sleep(1.5)
                    
                resp = requests.post(req_url, json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                
                if is_gemini:
                    content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    msg = {}
                else:
                    msg = data.get("choices", [{}])[0].get("message", {})
                    content = str(msg.get("content") or "").strip()
                    
                content = content.replace('```json', '').replace('```', '').strip()
                
                parsed = None
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    full_text = str(msg.get("reasoning_content") or "") + "\n" + content if not is_gemini else content
                    full_text = re.sub(r'<think>.*?</think>', '', full_text, flags=re.DOTALL)
                    blocks = re.findall(r'\{[^{}]*\}', full_text, re.DOTALL)
                    for block in reversed(blocks):
                        try:
                            temp = json.loads(block)
                            if "category" in temp and "summary" in temp:
                                parsed = temp
                                break
                        except json.JSONDecodeError:
                            continue
                            
                if parsed and "category" in parsed and "summary" in parsed:
                    parsed["_from_llm"] = True
                    return parsed
            except Exception as exc:
                err_detail = str(exc)
                if hasattr(exc, 'response') and exc.response is not None:
                    try:
                        resp_json = exc.response.json()
                        err_msg = resp_json.get("error", {}).get("message") or resp_json.get("error") or exc.response.text
                        if err_msg:
                            err_detail = f"{exc} ({str(err_msg)[:150]})"
                    except Exception:
                        if exc.response.text:
                            err_detail = f"{exc} ({exc.response.text[:150]})"
                label = provider.get('label', backend_id)
                provider_errors.append(f"{label}: {err_detail}")
                _safe_log(f"[yellow]{label} LLM fallback triggered for '{subject[:30]}...': {err_detail}[/yellow]")
                continue
                
        reasons_str = " | ".join(provider_errors) if provider_errors else "No LLM providers configured or available"
        _safe_log(f"[red]All LLMs failed or unreachable for '{subject[:30]}...'. Reasons: {reasons_str}[/red]")
        raise RuntimeError(f"AI Sync stopped while analyzing '{subject[:30]}...'. Reason: {reasons_str}")

    def sync_emails(self, days_back: int = 7, cancel_check=None, progress_callback=None) -> dict:
        if not self.email_address or not self.app_password:
            return {"error": "Gmail credentials not configured in .env."}

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.email_address, self.app_password)
            status, mailboxes = mail.list()
            all_mail_folder = None
            if status == "OK":
                for mailbox in mailboxes:
                    mb_str = mailbox.decode('utf-8', errors='ignore')
                    if '\\All' in mb_str:
                        match = re.search(r'\"/\"\s+(.+)$', mb_str)
                        if match:
                            all_mail_folder = match.group(1).strip()
                        break
            
            if all_mail_folder:
                status, _ = mail.select(all_mail_folder)
                if status != "OK":
                    mail.select("inbox")
            else:
                status, _ = mail.select('"[Gmail]/All Mail"')
                if status != "OK":
                    mail.select("inbox")
            
            date_since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, f'(SINCE "{date_since}")')
            
            if status != "OK":
                return {"error": "Failed to search emails."}
                
            email_ids = messages[0].split()
            total_emails = len(email_ids)
            processed_count = 0
            new_emails = 0
            loop_index = 0
            
            with self._connect_db() as conn:
                self.repair_existing_emails(conn)
                for eid in email_ids:
                    loop_index += 1
                    if progress_callback:
                        progress_callback(loop_index, total_emails, new_emails)
                    if cancel_check and cancel_check():
                        _safe_log("[yellow]Sync cancelled by user![/yellow]")
                        break
                        
                    status, msg_data = mail.fetch(eid, "(X-GM-LABELS X-GM-THRID X-GM-MSGID RFC822)")
                    if status != "OK":
                        continue
                        
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            resp_text = response_part[0].decode('utf-8', errors='ignore')
                            
                            msg_id_match = re.search(r'X-GM-MSGID\s+(\d+)', resp_text)
                            gmail_hex_id = hex(int(msg_id_match.group(1)))[2:] if msg_id_match else None
                            
                            thrid_match = re.search(r'X-GM-THRID\s+(\d+)', resp_text)
                            gmail_thread_id = hex(int(thrid_match.group(1)))[2:] if thrid_match else None
                            
                            labels_match = re.search(r'X-GM-LABELS\s+\((.*?)\)', resp_text)
                            gmail_labels = labels_match.group(1).lower() if labels_match else ""

                            msg = email.message_from_bytes(response_part[1])
                            
                            message_id = msg.get("Message-ID", "")
                            if not message_id:
                                continue
                            
                            exists = conn.execute("SELECT 1 FROM emails WHERE message_id = ?", (message_id,)).fetchone()
                            if exists:
                                continue
                                
                            subject = _clean_header(msg.get("Subject", ""))
                            sender = _clean_header(msg.get("From", ""))
                            recipient = _clean_header(msg.get("To", ""))
                            cc = _clean_header(msg.get("Cc", ""))
                            date = _clean_header(msg.get("Date", ""))
                            
                            is_outbound = bool('\\sent' in gmail_labels or (self.email_address and self.email_address.lower() in sender.lower()))
                            is_forwarded = bool(subject.lower().startswith('fwd:') or subject.lower().startswith('fw:'))
                            is_reply = bool(subject.lower().startswith('re:'))
                            is_automated = bool(re.search(r'(no-reply|noreply|mailer-daemon|donotreply)', sender.lower()))
                            
                            has_attachments = False
                            has_calendar_invite = False
                            
                            for part in msg.walk():
                                ctype = part.get_content_type()
                                cdisp = str(part.get("Content-Disposition"))
                                if ctype in ['text/calendar', 'application/ics']:
                                    has_calendar_invite = True
                                if ('attachment' in cdisp or 'inline' in cdisp) and part.get_filename():
                                    has_attachments = True
                            
                            thread_context = ""
                            if gmail_thread_id:
                                try:
                                    prev_emails = conn.execute("""
                                        SELECT category, subject, snippet FROM emails 
                                        WHERE json_extract(payload_json, '$.gmail_thread_id') = ?
                                        ORDER BY parsed_timestamp ASC LIMIT 5
                                    """, (gmail_thread_id,)).fetchall()
                                    if prev_emails:
                                        thread_context = " | ".join([f"[{s[0].upper()}] {s[1][:30]} - {s[2][:100]}" for s in prev_emails])
                                except Exception:
                                    pass
                            
                            body = self._truncate_text(self._get_body(msg))
                            
                            _safe_log(f"Analyzing email: {subject[:50]}...")
                            analysis = self._analyze_email_with_llm(
                                subject, sender, recipient, cc, body, 
                                is_outbound, is_forwarded, is_reply, is_automated, 
                                has_attachments, has_calendar_invite, thread_context
                            )
                            
                            analysis = _refine_email_analysis(subject, sender, recipient, body, is_outbound, analysis, from_llm=analysis.get("_from_llm", False))
                            category = analysis.get("category", "Other")
                            company = analysis.get("company_name")
                            summary = analysis.get("summary", subject)
                            
                            linked_job_key = None
                            linked_job_title = None
                            
                            def _norm(t): return re.sub(r'[^a-z0-9]', '', str(t).lower()) if t else ""
                            
                            domain_match = re.search(r'@([\w.-]+)', sender)
                            sender_domain = domain_match.group(1).split('.')[0] if domain_match else ""
                            
                            ignore_domains = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "aol", "live", "msn"}
                            
                            if category in ["Applied", "Review", "Interview", "Rejected"]:
                                norm_sender_domain = _norm(sender_domain)
                                norm_llm_company = _norm(company)
                                norm_llm_title = _norm(analysis.get("job_title"))
                                
                                if norm_sender_domain in ignore_domains:
                                    norm_sender_domain = ""
                                
                                applied_jobs = conn.execute("""
                                    SELECT j.job_key, j.title, j.company
                                    FROM jobs j
                                    JOIN applications a ON j.job_key = a.job_key
                                    ORDER BY a.applied_at DESC
                                """).fetchall()
                                
                                for j_key, j_title, j_comp in applied_jobs:
                                    norm_db_comp = _norm(j_comp)
                                    norm_db_title = _norm(j_title)
                                    
                                    match = False
                                    if norm_sender_domain and len(norm_sender_domain) > 2 and (norm_sender_domain in norm_db_comp or norm_db_comp in norm_sender_domain):
                                        match = True
                                    elif norm_llm_company and len(norm_llm_company) > 2 and (norm_llm_company in norm_db_comp or norm_db_comp in norm_llm_company):
                                        match = True
                                    elif norm_llm_title and len(norm_llm_title) > 4 and (norm_llm_title in norm_db_title or norm_db_title in norm_llm_title):
                                        match = True
                                        
                                    if match:
                                        linked_job_key, linked_job_title = j_key, j_title
                                        _safe_log(f"Linked email to job: {linked_job_title}")
                                        break
                            
                            payload = {
                                "subject": subject,
                                "sender": sender,
                                "recipient": recipient,
                                "cc": cc,
                                "is_outbound": is_outbound,
                                "is_forwarded": is_forwarded,
                                "is_reply": is_reply,
                                "is_automated": is_automated,
                                "has_attachments": has_attachments,
                                "has_calendar_invite": has_calendar_invite,
                                "date": date,
                                "body": body[:500],
                                "analysis": analysis,
                                "gmail_hex_id": gmail_hex_id,
                                "gmail_thread_id": gmail_thread_id,
                                "linked_job_key": linked_job_key,
                                "linked_job_title": linked_job_title
                            }
                            
                            parsed_ts = None
                            try:
                                parsed_tuple = email.utils.parsedate_tz(date)
                                if parsed_tuple:
                                    parsed_ts = int(email.utils.mktime_tz(parsed_tuple))
                            except Exception:
                                pass
                                
                            conn.execute("""
                                INSERT INTO emails (
                                    message_id, date, sender, subject, category, company_name, snippet, read_status, payload_json, parsed_timestamp
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                message_id, date, sender, subject, category, company, summary, 
                                1,
                                json.dumps(payload),
                                parsed_ts
                            ))
                            conn.commit()
                            new_emails += 1
                            processed_count += 1

                        
            mail.close()
            mail.logout()
            return {"status": "success", "new_emails": new_emails}
            
        except Exception as e:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass
            return {"error": str(e), "new_emails": new_emails, "status": "error"}

if __name__ == "__main__":
    service = GmailService()
    print(service.sync_emails(days_back=1))
