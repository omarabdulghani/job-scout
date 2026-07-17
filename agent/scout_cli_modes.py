LINKEDIN_MODE = "linkedin"
INDEED_MODE = "indeed"


def add_board_mode_arguments(parser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--linkedin",
        action="store_true",
        help="Run the existing LinkedIn scout flow. This is the default.",
    )
    group.add_argument(
        "--indeed",
        action="store_true",
        help="Run Indeed Netherlands description extraction.",
    )


def resolve_board_mode(args) -> str:
    return INDEED_MODE if getattr(args, "indeed", False) else LINKEDIN_MODE


def board_display_name(board_mode: str) -> str:
    return "Indeed" if board_mode == INDEED_MODE else "LinkedIn"


def requires_description_only(board_mode: str) -> bool:
    return board_mode == INDEED_MODE


def supported_browser_executable(browser_name: str, executable_path: str | None) -> tuple[str | None, str]:
    browser = (browser_name or "chromium").strip().lower()
    executable = (executable_path or "").strip()
    if browser == "firefox" and executable:
        return None, (
            "Installed Firefox binaries are not controllable by this Playwright-based scout. "
            "Using Playwright's bundled Firefox with the dedicated profile instead."
        )
    return executable or None, ""


def default_browser_profile_dir(board_mode: str, browser_name: str) -> str:
    board = (board_mode or LINKEDIN_MODE).strip().lower()
    browser = (browser_name or "chromium").strip().lower()
    if board == LINKEDIN_MODE:
        return "data/browser_profile"
    if browser == "firefox":
        return "data/indeed_playwright_firefox_profile"
    return "data/indeed_browser_profile"
