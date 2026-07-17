# 05 - Frontend: Vanilla JS State Management Refactoring Plan

## 1. The Core Vulnerability: DOM Manipulation Spaghetti & Desync
Currently, the live dashboard relies entirely on "Vanilla Javascript" (plain JS without a framework). Files like `dashboard/app.js` manually find HTML elements, mutate their text, and physically move HTML nodes around the screen when a job's status changes.

**Why this is dangerous:**
1. **State Desync (UI Bugs)**: When you mark a job as "Rejected", the code has to manually:
   - Remove the HTML card from the "Applied" column.
   - Create a new HTML card in the "Rejected" column.
   - Update the global `jobs` array in memory.
   - Re-calculate and update the text of the status counters.
   *If any one of these 4 steps fails, what you see on the screen is no longer what is actually saved in the database.*
2. **Memory Leaks**: Attaching thousands of click event listeners to job cards (for the Easy Apply modals, status dropdowns, etc.) without properly cleaning them up when the DOM changes will eventually crash the browser tab.
3. **Feature Velocity**: Adding complex features (like multi-select bulk actions or advanced nested filters) becomes a nightmare of `document.getElementById` logic.

## 2. The Implementation Plan for the Fix
*When we decide to execute this fix, we will isolate this work on a feature branch (per `EXECUTION_PROTOCOL.md`). We want to introduce a reactive "State Store" without ruining the lightweight, build-free nature of the app (we do not want to force you to install Node.js/Webpack/React).*

### Step 1: Introduce a Lightweight Reactive Framework
Instead of a heavy framework like React or Angular, we will import **Alpine.js** or **Preact** directly via a CDN tag in `recommended_jobs_dashboard.html`. This gives us the power of a reactive framework without needing a build step or compilation.

### Step 2: Implement the Central State Store
We will create a single source of truth: `dashboard/store.js`.
This store will hold the raw data arrays:
```javascript
const store = {
    jobs: [],
    filters: { text: "", status: "APPLY_FIRST" },
    activeJobModal: null
};
```

### Step 3: Data-Binding the HTML
We will rewrite the HTML templates to strictly bind to the state store. 
Instead of writing manual Javascript to update a counter, we will bind the HTML directly to the array length:
```html
<!-- Example Alpine.js syntax -->
<span class="counter" x-text="store.jobs.filter(j => j.status === 'APPLY_FIRST').length"></span>
```
When `store.jobs` updates via the backend API, the UI counter updates *automatically*. We delete hundreds of lines of manual UI update code.

### Step 4: Refactor Event Dispatching
Instead of attaching click listeners to individual buttons, we will implement a centralized "Action Dispatcher". Clicking "Reject" on a job simply calls `dispatch('UPDATE_JOB_STATUS', { id: 123, status: 'REJECTED' })`. The store handles the API call and updates the data, and the UI reacts automatically.

## 3. Verification & Safeguards
Before merging this massive UI rewrite, we will load a local database of 2,000 jobs. We will test every interactive element (filtering, sorting, updating status, opening modals, exporting PDFs) to ensure feature parity with the old Vanilla JS implementation. We will monitor browser RAM usage to confirm the memory leak risks have been eliminated.
