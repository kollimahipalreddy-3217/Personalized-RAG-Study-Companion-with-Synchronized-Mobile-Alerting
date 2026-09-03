// ============================================================
// script.js — Desktop Frontend Interaction & Real-Time Telemetry Controller
// Personalized RAG Study Companion with Synchronized Mobile Alerting
// Application Interface: StudyEdge AI
// ============================================================

// ─────────────────────────────────────────
// Global Toast Helper
// ─────────────────────────────────────────
var _toastTimer = null;
function showToast(msg, type) {
 const el = document.getElementById('toast');
 if (!el) return;
 const txt = document.getElementById('toastText');
 if (txt) txt.textContent = msg;
 el.style.display = 'flex';
 if (_toastTimer) clearTimeout(_toastTimer);
 _toastTimer = setTimeout(closeToast, 5000);
}
function closeToast() {
 const el = document.getElementById('toast');
 if (el) el.style.display = 'none';
}

// ─────────────────────────────────────────
// Application State
// ─────────────────────────────────────────
const S = {
 studentId : localStorage.getItem('student_id') || '1',
 studentName : localStorage.getItem('student_name') || 'Student',
 sessionId : localStorage.getItem('session_id') || null,
 currentView : 'home',
 notes : JSON.parse(localStorage.getItem('studyNotes') || '[]'),
 currentNoteId: null,

 // Model preferences per task (key = task name used in backend)
 modelConfig : JSON.parse(localStorage.getItem('modelConfig') || JSON.stringify({
 qa : 'mistral',
 summary : 'mistral',
 questions: 'mistral',
 analytics: 'llama3'
 })),

 // Active test state
 selectedTestLength: 16,
 timerMode : 'timed', // 'timed' or 'untimed'
 timeLimitMinutes : 20,
 currentTest : null,

 isSpeaking : false,
 pomodoroRound: 0,

 // Currently active model (last used for any task)
 activeModelName: null,
 activeModelTask: null,
 remindersPaused: false,
};

// Global Chart Instances (must be destroyed before re-rendering)
var radarChartInst = null;
var trendChartInst = null;
var forgettingChartInst = null;

// Global Test & Timer State (hoisted at top to prevent TDZ errors)
var _testLoadingTimerInterval = null;
var _testLoadingElapsedSecs = 0;
var _testPollInterval = null;
var _activeExamTimerInterval = null;
var _testSessionActive = false;
var PAUSED_TEST_KEY = 'study_edge_paused_test';

function _stopActiveExamTimer() {
 if (_activeExamTimerInterval) {
 clearInterval(_activeExamTimerInterval);
 _activeExamTimerInterval = null;
 }
 if (typeof S !== 'undefined' && S && S.currentTest && S.currentTest.timerInterval) {
 clearInterval(S.currentTest.timerInterval);
 S.currentTest.timerInterval = null;
 }
}

// ─────────────────────────────────────────
// Socket.IO Real time (safe fallback)
// ─────────────────────────────────────────
var socket = (typeof io !== 'undefined')
 ? io({ transports: ['polling', 'websocket'], timeout: 3000 })
 : {
 on: function() {},
 emit: function() {},
 off: function() {},
 connected: false,
 id: ''
 };

if (socket && typeof socket.on === 'function') {
 socket.on('connect', () => {
 console.log('[WS] Connected');
 if (S.sessionId) socket.emit('rejoin', { session_id: S.sessionId });
 });
}

socket.on('plans_updated', data => {
 if (data && data.student_id && String(data.student_id) !== String(S.studentId || 1)) return;
 console.log('[Web WS] plans_updated event:', data);
 loadTodayPlans();
 loadUpcomingPlans();
 });

 socket.on('timer_tick', data => {
 if (!S.sessionId || String(data.session_id) !== String(S.sessionId)) {
 S.sessionId = data.session_id;
 localStorage.setItem('session_id', S.sessionId);
 const pnl = document.getElementById('sessionStartPanel');
 if (pnl) pnl.style.display = 'none';
 const act = document.getElementById('activeSessionInfo');
 if (act) act.style.display = 'block';
 const atn = document.getElementById('activeTopicName');
 if (atn && data.topic) atn.textContent = data.topic;
 }
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = data.time_str || '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = (data.progress_pct || 0) + '%';
 const lbl = document.getElementById('timerLabel');
 if (lbl) lbl.textContent = data.is_break
 ? (data.break_type === 'long' ? 'LONG BREAK' : 'SHORT BREAK')
 : 'FOCUS SESSION';

 S.isBreakRunning = !!data.is_break;
 const bBtn = document.getElementById('breakBtn');
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (data.is_break) {
 if (bBtn) bBtn.style.display = 'none';
 if (cbBtn) cbBtn.style.display = 'inline-flex';
 } else {
 if (bBtn) bBtn.style.display = 'inline-flex';
 if (cbBtn) cbBtn.style.display = 'none';
 }

 const currentRound = data.round || 1;
 updateRoundDots(currentRound);

 // Dynamically update pomodoro counter at top left!
 const pmCount = document.getElementById('pomodoroCount');
 if (pmCount) pmCount.textContent = `R${currentRound}`;
 const pmLbl = document.getElementById('pomodoroStatLbl');
 if (pmLbl) pmLbl.textContent = 'Active Round';

 const sBtn = document.getElementById('startBtn');
 if (sBtn) sBtn.style.display = 'none';
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'inline-flex';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'inline-flex';

 // Live Synchronized AI Output Studio Banner!
 updateCurriculumBannerLive(data);
});

socket.on('timer_paused', data => {
 if (String(data.session_id) !== String(S.sessionId)) return;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Resume';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp && data.time_str) timerDisp.textContent = data.time_str;
 updateCurriculumBannerPaused(data);
 showToast(' Timer paused.');
});

socket.on('timer_reset', data => {
 if (String(data.session_id) !== String(S.sessionId)) return;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp && data.time_str) timerDisp.textContent = data.time_str;
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
 const endSpBtn = document.getElementById('endSprintBtn');
 if (endSpBtn) endSpBtn.style.display = 'none';
 resetCurriculumBannerToIdle();
 showToast(' Timer reset.');
});

socket.on('sprint_ended', data => {
 if (String(data.session_id) !== String(S.sessionId)) return;
 S.isSprintRunning = false;
 S.isSprintPaused = false;
 S.isBreakRunning = false;
 S.lastTimeStr = data.time_str;

 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const endSpBtn = document.getElementById('endSprintBtn');
 if (endSpBtn) endSpBtn.style.display = 'none';
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp && data.time_str) timerDisp.textContent = data.time_str;
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';

 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) {
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }
 showToast(' Sprint ended. Notes and studio remain open!', 'info');
});

socket.on('timer_done', data => {
 if (String(data.session_id) !== String(S.sessionId)) return;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 document.getElementById('pauseBtn').style.display = 'none';
 document.getElementById('timerDisplay').textContent = data.is_break ? '25:00' : 'Done!';
 showToast(data.message || ' Timer complete!');

 playChimeSound();
 triggerVibration([400, 200, 400, 200, 500]);

 if (!data.is_break) {
 S.pomodoroRound = (S.pomodoroRound % 4) + 1;
 updateRoundDots(S.pomodoroRound);
 const pCount = document.getElementById('pomodoroCount');
 if (pCount) pCount.textContent = S.pomodoroRound;
 const lbBtn = document.getElementById('longBreakBtn');
 if (lbBtn) lbBtn.style.display = S.pomodoroRound % 4 === 0 ? 'inline-flex' : 'none';
 const topic = document.getElementById('activeTopicName')?.textContent || 'your topic';
 renderRoundCompleteCard(topic, S.pomodoroRound);
 } else {
 const lbl = document.getElementById('timerLabel');
 if (lbl) lbl.textContent = 'FOCUS SESSION';
 document.getElementById('timerDisplay').textContent = '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
 }
 refreshStats();
});

socket.on('session_started', data => {
 if (data.student_id && String(data.student_id) !== String(S.studentId || 1)) return;
 console.log('[Desktop WS] session_started event received:', data);
 S.sessionId = data.session_id;
 localStorage.setItem('session_id', S.sessionId);

 const pnl = document.getElementById('sessionStartPanel');
 if (pnl) pnl.style.display = 'none';
 const act = document.getElementById('activeSessionInfo');
 if (act) act.style.display = 'block';
 const atn = document.getElementById('activeTopicName');
 if (atn && data.topic) atn.textContent = data.topic;

 fetchInteractiveMilestones(data.session_id, data.topic, data.doc_name);
 syncActiveCurriculumDesktop(data.session_id, data.topic, data.doc_name);
 loadTodayPlans();
 loadUpcomingPlans();
 refreshStats();
 showToast(`▶ Active session updated: "${data.topic}"`);
});

socket.on('milestones_updated', data => {
 if (data.session_id && String(data.session_id) === String(S.sessionId)) {
 console.log('[Desktop WS] milestones_updated received:', data.milestones);
 renderDesktopMilestones(data.milestones);
 }
});

socket.on('checkpoint_updated', data => {
 if (data.session_id && String(data.session_id) === String(S.sessionId)) {
 console.log('[Desktop WS] checkpoint_updated received:', data);
 if (data.curriculum) {
 S.currentCurriculum = data.curriculum;
 renderCurriculumStudio(data.curriculum, S.currentRoundIdx || 0);
 }
 }
});

socket.on('curriculum_ready', data => {
 if (data.student_id && String(data.student_id) !== String(S.studentId || 1)) return;
 console.log('[Desktop WS] curriculum_ready event received:', data);
 S.sessionId = data.session_id;
 localStorage.setItem('session_id', S.sessionId);
 S.currentCurriculum = data.curriculum;
 renderCurriculumStudio(data.curriculum, 0);
 startSprintFromCurriculum(0);
 showToast(`🎯 AI Curriculum ready & Sprint 1 started for "${data.topic}"!`);
});

socket.on('session_ended', data => {
 if (data.student_id && String(data.student_id) !== String(S.studentId || 1)) return;
 console.log('[Desktop WS] session_ended event received:', data);

 if (typeof _curriculumAbortController !== 'undefined' && _curriculumAbortController) {
 try { _curriculumAbortController.abort(); } catch (e) {}
 _curriculumAbortController = null;
 }

 S.sessionId = null;
 S.currentCurriculum = null;
 S.isSprintRunning = false;
 S.isSprintPaused = false;
 S.isBreakRunning = false;
 S.pomodoroRound = 0;
 localStorage.removeItem('session_id');

 // Reset Pomodoro count and label at top left!
 const pCount = document.getElementById('pomodoroCount');
 if (pCount) pCount.textContent = '0';
 const pLbl = document.getElementById('pomodoroStatLbl');
 if (pLbl) pLbl.textContent = 'Pomodoros';
 updateRoundDots(0);

 const pnl = document.getElementById('sessionStartPanel');
 if (pnl) pnl.style.display = 'block';
 const act = document.getElementById('activeSessionInfo');
 if (act) act.style.display = 'none';
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = '—';

 const mList = document.getElementById('sessionMilestonesList');
 if (mList) mList.innerHTML = '<div style="font-size:0.75rem;color:var(--muted);text-align:center;padding:8px">No active study session.</div>';

 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const bBtn = document.getElementById('breakBtn');
 if (bBtn) bBtn.style.display = 'inline-flex';
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (cbBtn) cbBtn.style.display = 'none';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'none';
 const examBtn = document.getElementById('btnExamFromSession');
 if (examBtn) examBtn.style.display = 'none';

 resetCurriculumBannerToIdle();

 const spinEl = document.getElementById('studioLoading');
 if (spinEl) spinEl.style.display = 'none';

 const outEl = document.getElementById('studioOutput');
 if (outEl) {
 outEl.style.display = 'block';
 outEl.classList.remove('raw-text');
 outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }

 loadTodayPlans();
 loadUpcomingPlans();
 showToast('Session ended cleanly.');
 refreshStats();
});

socket.on('reminders_status_changed', data => {
 if (data && data.student_id && String(data.student_id) !== String(S.studentId || 1)) return;
 console.log('[Desktop WS] reminders_status_changed event:', data);
 if (typeof updateRemindersUI === 'function') {
 updateRemindersUI(data);
 }
 if (data.paused) {
 const existing = document.getElementById('reminderBanner');
 if (existing) existing.remove();
 if (navigator.serviceWorker && navigator.serviceWorker.controller) {
 navigator.serviceWorker.controller.postMessage({ type: 'CANCEL_ALL_LOCAL_ALARMS' });
 }
 }
});

// ─────────────────────────────────────────
// Initialization
// ─────────────────────────────────────────
function initApp() {
 if (!S.studentId || !S.studentName) {
 S.studentId = localStorage.getItem('student_id') || '1';
 S.studentName = localStorage.getItem('student_name') || 'Student';
 }

 // Immediately apply locally cached pause status so UI never flickers to active on refresh
 const savedPaused = localStorage.getItem('studyedge_reminders_paused') === 'true';
 const savedMins = parseInt(localStorage.getItem('studyedge_reminders_mins') || '-1');
 if (savedPaused) {
 updateRemindersUI({ paused: true, remaining_minutes: savedMins });
 }

 fetchRemindersStatus();
 initReminderPolling();

 const navName = document.getElementById('navStudentName');
 if (navName) navName.textContent = S.studentName || 'Student';
 const hsn = document.getElementById('homeStudentName');
 if (hsn) hsn.textContent = S.studentName || 'Student';

 // Restore model dropdowns from saved config
 restoreModelDropdowns();

 // Restore active session indicator
 if (S.sessionId) {
 const ssp = document.getElementById('sessionStartPanel');
 if (ssp) ssp.style.display = 'none';
 const asi = document.getElementById('activeSessionInfo');
 if (asi) asi.style.display = 'block';
 refreshStats();
 }

 loadDocuments(); // Always load docs on startup
 loadDailyQuote();
 renderNotesList();
 loadOverallReports();
 checkPausedTestOnLoad();

 const dateStr = new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
 const ldEl = document.getElementById('liveDate');
 if (ldEl) ldEl.textContent = dateStr;

 const chatInput = document.getElementById('chatInput');
 if (chatInput) chatInput.addEventListener('keydown', e => {
 if (e.ctrlKey && e.key === 'Enter') sendQuestion();
 });

 // Service Worker
 if ('serviceWorker' in navigator) {
 navigator.serviceWorker.register('/sw.js', { scope: '/' })
 .then(r => console.log('[SW]', r.scope))
 .catch(e => console.warn('[SW] Error:', e));
 }

 if (localStorage.getItem('pushEnabled')) {
 const btn = document.getElementById('enablePushBtn');
 if (btn) { btn.innerHTML = '<i class="bi bi-bell-fill"></i> Notifications Enabled'; btn.disabled = true; }
 }

 // Pre-load chat threads
 loadChatThreads();

 // Multi-device active session sync
 syncActiveSessionDesktop();
 setInterval(syncActiveSessionDesktop, 4000);
 syncActiveCurriculumDesktop();

 // Poll Ollama model status immediately and every 8s
 pollModelStatus();
 setInterval(pollModelStatus, 8000);

 // Initialize UI adjustability & Sources dropdown
 initStudioSplitter();
 initSourcesDropdownEvents();
 initPlanDateTimeLimits();
 initNetworkStatusWatcher();
}

function initNetworkStatusWatcher() {
 const updateOnlineStatus = () => {
 const ind = document.getElementById('offlineIndicator');
 if (!navigator.onLine) {
 if (ind) ind.style.display = 'inline-flex';
 showToast(' Offline Mode: Internet is disconnected. Local AI models and notes are fully active.', 'warning');
 } else {
 if (ind) ind.style.display = 'none';
 }
 };

 window.addEventListener('online', () => {
 updateOnlineStatus();
 showToast(' Internet connection restored. Online web search active.', 'success');
 });

 window.addEventListener('offline', () => {
 updateOnlineStatus();
 });

 if (!navigator.onLine) {
 updateOnlineStatus();
 }
}

// Execute immediately if DOM already interactive/loaded, otherwise wait for event
if (document.readyState === 'loading') {
 document.addEventListener('DOMContentLoaded', initApp);
} else {
 initApp();
}

// ─────────────────────────────────────────
// Model Status Polling & Active Model Badge
// ─────────────────────────────────────────
function pollModelStatus() {
 fetch('/startup-status')
 .then(r => r.json())
 .then(data => {
 const ready = data.ready || [];
 const installed = data.installed || ready;
 const modelKeys = [
 { key: 'gemma3', match: 'gemma3' },
 { key: 'phi3', match: 'phi3' },
 { key: 'mistral', match: 'mistral' },
 { key: 'llama3', match: 'llama3' }
 ];

 // Current active models in task dropdowns
 const activeTaskModels = Object.values(S.modelConfig || {});

 modelKeys.forEach(m => {
 const el = document.getElementById(`mstat-${m.key}`);
 if (!el) return;
 const isReady = installed.some(name =>
 name.toLowerCase().replace(/[:\-_]/g, '').includes(m.match)
 );
 const isConfiguredActive = activeTaskModels.some(name =>
 name.toLowerCase().replace(/[:\-_]/g, '').includes(m.match)
 );

 if (isConfiguredActive && isReady) {
 el.textContent = ' Active';
 el.style.color = 'var(--primary)';
 el.style.fontWeight = '700';
 } else if (isReady) {
 el.textContent = ' Ready';
 el.style.color = 'var(--success)';
 el.style.fontWeight = '600';
 } else {
 el.textContent = '—';
 el.style.color = 'var(--muted)';
 el.style.fontWeight = '500';
 }
 });

 // Show which model is currently active
 updateActiveModelBar();
 })
 .catch(() => {
 ['gemma3', 'phi3', 'mistral', 'llama3'].forEach(m => {
 const el = document.getElementById(`mstat-${m}`);
 if (el) { 
 el.textContent = 'Offline'; 
 el.style.color = 'var(--danger)'; 
 el.style.fontWeight = '600';
 }
 });
 });
}

/**
 * Updates the "Last Active" model badge at the bottom of the right panel.
 */
function updateActiveModelBar() {
 const labelEl = document.getElementById('activeModelLabel');
 const taskEl = document.getElementById('activeModelTask');
 const task = S.activeModelTask || 'Ready (Default)';
 const model = S.activeModelName || S.modelConfig.qa || 'mistral';
 if (labelEl) labelEl.textContent = model;
 if (taskEl) taskEl.textContent = `Task: ${task}`;
}

// ─────────────────────────────────────────
// Model Switching
// ─────────────────────────────────────────
function restoreModelDropdowns() {
 const map = { qa: 'modelQA', summary: 'modelSum', questions: 'modelQ', analytics: 'modelA' };
 Object.entries(map).forEach(([task, elemId]) => {
 const el = document.getElementById(elemId);
 if (el && S.modelConfig[task]) {
 el.value = S.modelConfig[task];
 }
 });
 const tag = document.getElementById('analyticsModelTag');
 if (tag && S.modelConfig.analytics) tag.textContent = S.modelConfig.analytics;
}

function switchModel(task, modelName) {
 S.modelConfig[task] = modelName;
 localStorage.setItem('modelConfig', JSON.stringify(S.modelConfig));

 // Update active model display immediately
 const taskLabels = { qa: 'Q&A', summary: 'Summary', questions: 'Test Gen', analytics: 'Analytics' };
 S.activeModelTask = taskLabels[task] || task;
 S.activeModelName = modelName;
 updateActiveModelBar();

 // Update analytics tag
 if (task === 'analytics') {
 const tag = document.getElementById('analyticsModelTag');
 if (tag) tag.textContent = modelName;
 }

 // Refresh status labels
 pollModelStatus();

 // Sync to backend
 fetch('/switch-model', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ task, model: modelName })
 })
 .then(r => r.json())
 .then(() => showToast(` ${S.activeModelTask} model switched to: ${modelName}`))
 .catch(() => showToast(` Selected ${modelName} for ${task} (offline sync)`));
}

// ─────────────────────────────────────────
// View Navigation
// ─────────────────────────────────────────
function setView(view) {
 S.currentView = view;
 ['home', 'planner', 'test', 'reports', 'chat'].forEach(v => {
 const el = document.getElementById(`view-${v}`);
 if (el) el.style.display = v === view ? 'flex' : 'none';
 const btn = document.getElementById(`btn-${v}`);
 if (btn) btn.classList.toggle('active', v === view);
 });
 loadDocuments();
 pollModelStatus();
 if (view === 'reports' || view === 'home') loadOverallReports();
 if (view === 'test') { populateTestDocSelect(); checkPausedTestOnLoad(); }
 if (view === 'planner') { loadTodayPlans(); loadUpcomingPlans(); }
 if (view === 'chat') { initReminderPolling();
 initChatWorkspace(); }
}

// ─────────────────────────────────────────
// MCQ Test Length & Timer Mode Selection
// ─────────────────────────────────────────
function selectTestLength(n, el) {
 S.selectedTestLength = parseInt(n);
 const hidEl = document.getElementById('selectedTestLength');
 if (hidEl) hidEl.value = n;
 document.querySelectorAll('.test-len-card').forEach(c => c.classList.remove('active'));
 if (el) el.classList.add('active');

 // Dynamically set smart default timer duration for chosen question length
 const defaultMinsMap = { 16: 20, 32: 40, 48: 60, 60: 80 };
 const recMins = defaultMinsMap[S.selectedTestLength] || Math.round(S.selectedTestLength * 1.3);
 setTimerDuration(recMins);
}

function setTimerMode(mode) {
 S.timerMode = mode;
 const timedRadio = document.getElementById('timerModeTimedRadio');
 const untimedRadio = document.getElementById('timerModeUntimedRadio');
 const timedLbl = document.getElementById('timerModeTimedLabel');
 const untimedLbl = document.getElementById('timerModeUntimedLabel');
 const panel = document.getElementById('timedConfigPanel');

 if (mode === 'timed') {
 if (timedRadio) timedRadio.checked = true;
 if (timedLbl) timedLbl.classList.add('active');
 if (untimedLbl) untimedLbl.classList.remove('active');
 if (panel) panel.style.display = 'flex';
 } else {
 if (untimedRadio) untimedRadio.checked = true;
 if (untimedLbl) untimedLbl.classList.add('active');
 if (timedLbl) timedLbl.classList.remove('active');
 if (panel) panel.style.display = 'none';
 }
}

function selectTimerPreset(mins, el) {
 setTimerDuration(mins);
}

function onCustomTimerInput(input) {
 const mins = Math.max(1, Math.min(360, parseInt(input.value) || 1));
 setTimerDuration(mins, false);
}

function setTimerDuration(mins, updateInput = true) {
 S.timeLimitMinutes = parseInt(mins) || 20;
 if (updateInput) {
 const input = document.getElementById('customTimerInput');
 if (input) input.value = S.timeLimitMinutes;
 }
 document.querySelectorAll('.btn-timer-preset').forEach(btn => {
 btn.classList.toggle('active', parseInt(btn.dataset.mins) === S.timeLimitMinutes);
 });
 updatePerQuestionHint();
}

function updatePerQuestionHint() {
 const hint = document.getElementById('perQuestionTimeHint');
 if (!hint) return;
 const numQ = S.selectedTestLength || 16;
 const mins = S.timeLimitMinutes || 20;
 const perQ = (mins / numQ).toFixed(1);
 hint.textContent = `~${perQ} min / question`;
}

// ─────────────────────────────────────────
// Test Document & Chapter Scope Selector
// ─────────────────────────────────────────
S.chapterScopeMode = 'all'; // 'all' or 'custom'
S.docChapters = [];
S.selectedChapterIds = new Set();

function populateTestDocSelect() {
 fetch('/documents')
 .then(r => r.json())
 .then(data => {
 const sel = document.getElementById('testDocSelect');
 if (!sel) return;
 const docs = data.documents || [];
 if (docs.length) {
 sel.innerHTML = docs.map(d => `<option value="${d}">${d}</option>`).join('');
 onTestDocSelected();
 } else {
 sel.innerHTML = '<option value="" disabled selected>No documents uploaded yet — add a PDF first</option>';
 }
 })
 .catch(() => {});
}

function onTestDocSelected() {
 const sel = document.getElementById('testDocSelect');
 const docName = sel ? sel.value : '';
 if (!docName) return;
 loadDocumentChapters(docName);
}

function setChapterScopeMode(mode) {
 S.chapterScopeMode = mode;
 const allRadio = document.getElementById('scopeAllRadio');
 const custRadio = document.getElementById('scopeCustomRadio');
 const allLbl = document.getElementById('scopeAllLabel');
 const custLbl = document.getElementById('scopeCustomLabel');
 const panel = document.getElementById('customChapterPanel');
 const hint = document.getElementById('genScopeHint');

 if (mode === 'all') {
 if (allRadio) allRadio.checked = true;
 if (allLbl) allLbl.classList.add('active');
 if (custLbl) custLbl.classList.remove('active');
 if (panel) panel.style.display = 'none';
 if (hint) hint.innerHTML = '<i class="bi bi-shield-check"></i> Entire Book: Guaranteed 100% topic &amp; category coverage across all chapters';
 } else {
 if (custRadio) custRadio.checked = true;
 if (custLbl) custLbl.classList.add('active');
 if (allLbl) allLbl.classList.remove('active');
 if (panel) panel.style.display = 'block';
 updateChapterSummaryUI();
 }
}

function loadDocumentChapters(docName) {
 const listEl = document.getElementById('chapterCheckboxList');
 if (!listEl) return;
 listEl.innerHTML = '<div class="chapter-loading-hint"><div class="spinner-sm"></div> Discovering document chapters &amp; sections...</div>';

 fetch(`/document-chapters/${encodeURIComponent(docName)}`)
 .then(r => r.json())
 .then(data => {
 S.docChapters = data.chapters || [];
 // Default to selecting all main chapters
 S.selectedChapterIds = new Set(
 S.docChapters.filter(c => c.is_main).map(c => c.id)
 );
 if (S.selectedChapterIds.size === 0 && S.docChapters.length) {
 S.selectedChapterIds = new Set(S.docChapters.map(c => c.id));
 }
 renderChapterCheckboxes();
 updateChapterSummaryUI();
 })
 .catch(err => {
 listEl.innerHTML = '<div class="hint" style="color:var(--muted)">Entire document will be used as a single continuous scope.</div>';
 });
}

function renderChapterCheckboxes() {
 const listEl = document.getElementById('chapterCheckboxList');
 if (!listEl) return;

 if (!S.docChapters.length) {
 listEl.innerHTML = '<div class="hint" style="padding:10px">No separate chapters detected. The full document will be studied.</div>';
 return;
 }

 listEl.innerHTML = S.docChapters.map(c => {
 const isChecked = S.selectedChapterIds.has(c.id);
 const subCount = c.subsections ? c.subsections.length : 0;
 const subHint = subCount > 0 ? `<span class="chapter-sub-count">• ${subCount} sub-topics</span>` : '';
 return `
 <div class="chapter-card-item ${isChecked ? 'selected' : ''}" onclick="toggleChapterCard('${c.id}', event)">
 <input type="checkbox" class="chapter-cb-box" id="cb-${c.id}" value="${c.id}" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation(); toggleChapterSelection('${c.id}')"/>
 <div class="chapter-card-body">
 <div class="chapter-card-title">${c.title}</div>
 <div class="chapter-card-meta">
 <span class="chapter-page-badge"><i class="bi bi-file-earmark-text"></i> Pages ${c.page_start}–${c.page_end} (${c.total_pages}p)</span>
 ${subHint}
 </div>
 </div>
 </div>
 `;
 }).join('');
}

function toggleChapterCard(chapId, e) {
 if (S.selectedChapterIds.has(chapId)) {
 S.selectedChapterIds.delete(chapId);
 } else {
 S.selectedChapterIds.add(chapId);
 }
 renderChapterCheckboxes();
 updateChapterSummaryUI();
}

function toggleChapterSelection(chapId) {
 if (S.selectedChapterIds.has(chapId)) {
 S.selectedChapterIds.delete(chapId);
 } else {
 S.selectedChapterIds.add(chapId);
 }
 renderChapterCheckboxes();
 updateChapterSummaryUI();
}

function selectAllChapters(select) {
 if (select) {
 S.selectedChapterIds = new Set(S.docChapters.map(c => c.id));
 } else {
 S.selectedChapterIds.clear();
 }
 renderChapterCheckboxes();
 updateChapterSummaryUI();
}

function updateChapterSummaryUI() {
 const sumEl = document.getElementById('chapterSelectionSummary');
 const hintEl = document.getElementById('genScopeHint');
 const numQ = S.selectedTestLength || 16;
 const count = S.selectedChapterIds.size;
 const total = S.docChapters.length;

 if (sumEl) {
 if (count === 0) {
 sumEl.innerHTML = `<span style="color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> No chapters selected (please select at least 1)</span>`;
 } else {
 const perChap = Math.max(1, Math.round(numQ / count));
 sumEl.innerHTML = `<span><i class="bi bi-check-circle-fill" style="color:var(--success)"></i> <b>${count} of ${total}</b> chapters selected (~${perChap} questions/chapter)</span>`;
 }
 }

 if (hintEl && S.chapterScopeMode === 'custom') {
 if (count === 0) {
 hintEl.innerHTML = `<span style="color:var(--danger)"> Select at least 1 chapter to generate a scoped test</span>`;
 } else {
 hintEl.innerHTML = `<i class="bi bi-bullseye"></i> Targeted Test: ${numQ} questions focused on ${count} selected chapter(s)`;
 }
 }
}

// ─────────────────────────────────────────
// MCQ Test Generation — ASYNC via SocketIO
// ─────────────────────────────────────────
function cancelTestGeneration() {
 if (_testPollInterval) { clearInterval(_testPollInterval); _testPollInterval = null; }
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 _stopActiveExamTimer();
 _testSessionActive = false;
 document.getElementById('testLoading').style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 pollModelStatus();
 showToast('Test generation cancelled.');
}

function _updateTestLoadingProgress(message, percent = null, batchInfo = null) {
 const msgEl = document.getElementById('testLoadingMsg');
 const barEl = document.getElementById('testLoadingProgressBar');
 const batchEl = document.getElementById('testLoadingBatchProgress');

 if (message && msgEl) {
 msgEl.textContent = message;
 }

 // Parse batch numbers like [2/4] or [1/4] if present in message
 const match = message ? message.match(/\[(\d+)\/(\d+)\]/) : null;
 if (match) {
 const current = parseInt(match[1]);
 const total = parseInt(match[2]);
 const pct = Math.min(95, Math.round((current / total) * 100));
 if (barEl) barEl.style.width = `${pct}%`;
 if (batchEl) batchEl.textContent = `Completed ${current} of ${total} chapter batches`;
 } else if (percent !== null && barEl) {
 barEl.style.width = `${percent}%`;
 }

 if (batchInfo && batchEl) {
 batchEl.textContent = batchInfo;
 }
}

socket.on('test_progress', data => {
 if (data.message) {
 _updateTestLoadingProgress(data.message);
 }
});

socket.on('test_ready', data => {
 if (_testSessionActive) return; // Prevent double invocation if already active
 if (_testPollInterval) { clearInterval(_testPollInterval); _testPollInterval = null; }
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 _stopActiveExamTimer();
 
 const barEl = document.getElementById('testLoadingProgressBar');
 if (barEl) barEl.style.width = '100%';

 setTimeout(() => {
 document.getElementById('testLoading').style.display = 'none';
 pollModelStatus();

 if (!data.questions || !data.questions.length) {
 _testSessionActive = false;
 showToast(' Test returned 0 questions. The document may be too short — try uploading more content.');
 document.getElementById('testSetup').style.display = 'block';
 return;
 }
 _testSessionActive = true;
 S.currentTest = _buildTestState(data);
 startTestTakingSession();
 }, 400);
});

socket.on('test_error', data => {
 if (_testPollInterval) { clearInterval(_testPollInterval); _testPollInterval = null; }
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 _stopActiveExamTimer();
 _testSessionActive = false;
 document.getElementById('testLoading').style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 pollModelStatus();
 showToast(` Test generation notice: ${data.error || 'Unknown error'}`);
});

var _testPollInterval = null;

function _buildTestState(data) {
 const numQ = data.questions ? data.questions.length : S.selectedTestLength;
 const docName = data.docName || document.getElementById('testDocSelect')?.value || '';
 const timerMode = (S.timerMode === 'untimed') ? 'untimed' : 'timed';
 const timeLimitMinutes = parseInt(S.timeLimitMinutes) || 20;
 const initialSeconds = (timerMode === 'timed') ? (timeLimitMinutes * 60) : 0;
 return {
 testId : data.testId || ('test-' + Date.now()),
 testType : data.testType || `${numQ}-Question ${timerMode === 'timed' ? 'Timed Exam' : 'Study Test'}`,
 docName,
 topic : docName.replace(/\.pdf$/i, '').replace(/_/g, ' '),
 totalQuestions : data.questions.length,
 questions : data.questions,
 answers : {},
 currentIndex : 0,
 timerMode : timerMode,
 timeLimitMinutes : timeLimitMinutes,
 timerSeconds : initialSeconds,
 totalElapsedSeconds: 0,
 timerInterval : null
 };
}

function generateTest() {
 try {
 _stopActiveExamTimer();
 _testSessionActive = false;

 const sel = document.getElementById('testDocSelect');
 const docName = sel ? sel.value : '';

 if (!docName) {
 showToast(' Please upload and select a study document first.');
 return;
 }

 if (S.chapterScopeMode === 'custom' && (!S.selectedChapterIds || S.selectedChapterIds.size === 0)) {
 showToast(' Please select at least one chapter or choose "Entire Book".');
 return;
 }

 const numQ = S.selectedTestLength || 16;
 const model = S.modelConfig.questions || 'mistral';

 // Update active model display
 S.activeModelName = model;
 S.activeModelTask = 'Test Gen';
 updateActiveModelBar();

 // Hide setup, show loading
 document.getElementById('testSetup').style.display = 'none';
 document.getElementById('testTakingContainer').style.display = 'none';
 document.getElementById('testResults').style.display = 'none';
 const loadEl = document.getElementById('testLoading');
 loadEl.style.display = 'block';
 const cleanName = docName.replace('.pdf', '').replace(/_/g, ' ');
 const numChaps = (S.selectedChapterIds && S.selectedChapterIds.size) ? S.selectedChapterIds.size : 0;
 const scopeText = S.chapterScopeMode === 'custom' ? `(${numChaps} Chapters)` : '(All Chapters)';
 
 _updateTestLoadingProgress(`Synthesizing ${numQ} questions on "${cleanName}" ${scopeText} with ${model}…`, 15, 'Preparing document passages...');
 document.getElementById('testLoadingModel').textContent = `Balanced across: Cognitive Memory, Logic, Critical Thinking & Creative Application`;

 // Start live elapsed timer
 if (_testLoadingTimerInterval) clearInterval(_testLoadingTimerInterval);
 _testLoadingElapsedSecs = 0;
 const timerEl = document.getElementById('testLoadingTimer');
 if (timerEl) timerEl.innerHTML = '<i class="bi bi-stopwatch"></i> Elapsed: 0s';
 _testLoadingTimerInterval = setInterval(() => {
 _testLoadingElapsedSecs++;
 const tEl = document.getElementById('testLoadingTimer');
 if (tEl) tEl.innerHTML = `<i class="bi bi-stopwatch"></i> Elapsed: ${_testLoadingElapsedSecs}s`;
 }, 1000);

 // Mark model as generating in status list
 ['gemma3', 'phi3', 'mistral', 'llama3'].forEach(m => {
 const el = document.getElementById(`mstat-${m}`);
 if (!el) return;
 if (model.toLowerCase().includes(m)) {
 el.textContent = ' Generating…';
 el.style.color = 'var(--warning)';
 }
 });

 const selectedChaps = (S.chapterScopeMode === 'custom' && S.selectedChapterIds && S.selectedChapterIds.size > 0)
 ? Array.from(S.selectedChapterIds)
 : [];

 let sid = '';
 try {
 if (typeof socket !== 'undefined' && socket && socket.connected) {
 sid = socket.id || '';
 }
 } catch (e) {}

 console.log('[generateTest] Sending request to /generate-test:', { docName, numQ, model, selectedChaps });

 fetch('/generate-test', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 doc_name : docName,
 num_questions : numQ,
 model,
 selected_chapters: selectedChaps,
 socket_id : sid
 })
 })
 .then(r => {
 console.log('[generateTest] /generate-test HTTP status:', r.status);
 if (!r.ok) throw new Error('HTTP ' + r.status);
 return r.json();
 })
 .then(data => {
 console.log('[generateTest] /generate-test response:', data);
 if (data.status === 'started' && data.job_id) {
 _startJobPolling(data.job_id);
 } else if (data.questions && data.questions.length) {
 if (_testSessionActive) return;
 _testSessionActive = true;
 _stopActiveExamTimer();
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 loadEl.style.display = 'none';
 pollModelStatus();
 S.currentTest = _buildTestState(data);
 startTestTakingSession();
 } else {
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 loadEl.style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 pollModelStatus();
 showToast(' Could not start test generation: ' + (data.error || 'Check Ollama status.'));
 }
 })
 .catch(err => {
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 loadEl.style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 pollModelStatus();
 console.error('[TEST ERROR]', err);
 showToast(' Cannot reach server: ' + err.message);
 });
 } catch (err) {
 console.error('[generateTest Fatal]', err);
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 document.getElementById('testLoading').style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 showToast(' Test generation error: ' + err.message);
 }
}

function _startJobPolling(jobId) {
 if (_testPollInterval) clearInterval(_testPollInterval);

 console.log('[POLL] Starting job polling for:', jobId);

 _testPollInterval = setInterval(() => {
 fetch(`/test-job/${jobId}`)
 .then(r => r.json())
 .then(data => {
 console.log('[POLL TICK]', jobId, data.status, data.progress, data.elapsed_seconds);
 if (data.status === 'running') {
 if (data.progress) {
 _updateTestLoadingProgress(data.progress);
 }
 if (typeof data.elapsed_seconds === 'number' && data.elapsed_seconds > _testLoadingElapsedSecs) {
 _testLoadingElapsedSecs = data.elapsed_seconds;
 const tEl = document.getElementById('testLoadingTimer');
 if (tEl) tEl.innerHTML = `<i class="bi bi-stopwatch"></i> Elapsed: ${_testLoadingElapsedSecs}s`;
 }
 return;
 }
 clearInterval(_testPollInterval);
 _testPollInterval = null;
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }

 const barEl = document.getElementById('testLoadingProgressBar');
 if (barEl) barEl.style.width = '100%';

 setTimeout(() => {
 document.getElementById('testLoading').style.display = 'none';
 pollModelStatus();

 if (data.status === 'error') {
 document.getElementById('testSetup').style.display = 'block';
 showToast(` Generation notice: ${data.error || 'Check server connection'}`);
 return;
 }

 if (data.status === 'done' || (data.questions && data.questions.length)) {
 if (_testSessionActive) return;
 _testSessionActive = true;
 _stopActiveExamTimer();
 S.currentTest = _buildTestState(data);
 startTestTakingSession();
 }
 }, 400);
 })
 .catch(err => {
 console.warn('[POLL ERR]', err);
 });
 }, 1500);
}



// ─────────────────────────────────────────
// Paused Test & Auto-Save Management
// ─────────────────────────────────────────
function savePausedTestToStorage(testState) {
 if (!testState || !testState.questions || !testState.questions.length) return;
 try {
 const dataToSave = {
 testId : testState.testId,
 testType : testState.testType,
 docName : testState.docName,
 topic : testState.topic,
 totalQuestions : testState.totalQuestions,
 questions : testState.questions,
 answers : testState.answers || {},
 currentIndex : testState.currentIndex || 0,
 timerMode : testState.timerMode || 'timed',
 timeLimitMinutes : testState.timeLimitMinutes || 20,
 timerSeconds : testState.timerSeconds || 0,
 totalElapsedSeconds: testState.totalElapsedSeconds || 0,
 pausedAt : new Date().toISOString()
 };
 localStorage.setItem(PAUSED_TEST_KEY, JSON.stringify(dataToSave));
 } catch (e) {
 console.warn('[STORAGE] Error saving paused test:', e);
 }
}

function clearPausedTestStorage() {
 localStorage.removeItem(PAUSED_TEST_KEY);
 const card = document.getElementById('pausedTestCard');
 if (card) card.style.display = 'none';
}

function checkPausedTestOnLoad() {
 try {
 const saved = localStorage.getItem(PAUSED_TEST_KEY);
 const card = document.getElementById('pausedTestCard');
 if (!saved || !card) {
 if (card) card.style.display = 'none';
 return;
 }
 const data = JSON.parse(saved);
 if (!data || !data.questions || !data.questions.length) {
 card.style.display = 'none';
 return;
 }

 const answeredCount = Object.keys(data.answers || {}).length;
 const isTimed = (data.timerMode === 'timed');
 const remainingOrElapsed = Math.max(0, data.timerSeconds || 0);
 const mins = String(Math.floor(remainingOrElapsed / 60)).padStart(2, '0');
 const secs = String(remainingOrElapsed % 60).padStart(2, '0');

 const timerInfoStr = isTimed
 ? ` <b>${mins}:${secs}</b> remaining (<b>${data.timeLimitMinutes || 20}m</b> Timed Exam)`
 : `️ <b>${mins}:${secs}</b> elapsed (Untimed Study)`;

 const subEl = document.getElementById('pausedTestInfo');
 if (subEl) {
 subEl.innerHTML = `Ongoing <b>${data.testType || 'Test'}</b> on "<b>${data.topic || 'Document'}</b>" &bull; <b>${answeredCount}/${data.totalQuestions}</b> answered &bull; ${timerInfoStr}`;
 }
 card.style.display = 'flex';
 } catch (e) {
 console.warn('[STORAGE] Failed to parse paused test:', e);
 }
}

function pauseTest() {
 const t = S.currentTest;
 if (!t) return;

 _stopActiveExamTimer();
 _testSessionActive = false;

 savePausedTestToStorage(t);

 document.getElementById('testTakingContainer').style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 checkPausedTestOnLoad();

 showToast(' Test paused! Your progress and elapsed time have been saved. Resume anytime.');
}

function updateActiveTimerDisplay(t) {
 if (!t) return;
 const isTimed = (t.timerMode === 'timed');
 const remainingOrElapsed = Math.max(0, t.timerSeconds || 0);
 const m = String(Math.floor(remainingOrElapsed / 60)).padStart(2, '0');
 const s = String(remainingOrElapsed % 60).padStart(2, '0');
 const textEl = document.getElementById('testTimerText');
 const timerDisp = document.getElementById('testTimerDisplay');
 const timerIcon = document.getElementById('testTimerIcon');

 if (textEl) textEl.textContent = `${m}:${s}`;
 if (timerIcon) {
 timerIcon.className = isTimed ? 'bi bi-hourglass-split' : 'bi bi-stopwatch';
 timerIcon.title = isTimed ? 'Remaining Time' : 'Elapsed Time (Unrestricted)';
 }

 if (timerDisp) {
 timerDisp.title = isTimed ? `Timed Exam: ${m}:${s} remaining` : `Unrestricted Study: ${m}:${s} elapsed`;
 if (isTimed) {
 if (remainingOrElapsed <= 60) {
 timerDisp.className = 'test-timer timer-danger';
 } else if (remainingOrElapsed <= 300) {
 timerDisp.className = 'test-timer timer-warning';
 } else {
 timerDisp.className = 'test-timer';
 }
 } else {
 timerDisp.className = 'test-timer';
 }
 }
}

function resumeTest() {
 let t = S.currentTest;
 if (!t || !t.questions || !t.questions.length) {
 try {
 const saved = localStorage.getItem(PAUSED_TEST_KEY);
 if (saved) {
 const parsed = JSON.parse(saved);
 t = {
 ...parsed,
 timerInterval: null
 };
 S.currentTest = t;
 }
 } catch (e) {
 console.error('[RESUME ERROR]', e);
 }
 }

 if (!t || !t.questions || !t.questions.length) {
 showToast(' No active paused test found.');
 return;
 }

 _stopActiveExamTimer();
 _testSessionActive = true;

 document.getElementById('testSetup').style.display = 'none';
 document.getElementById('pausedTestCard').style.display = 'none';
 document.getElementById('testResults').style.display = 'none';
 document.getElementById('testTakingContainer').style.display = 'block';

 document.getElementById('takingTestType').textContent = t.testType || 'Test';
 document.getElementById('takingTestTopic').textContent = t.topic || 'General Study';

 // Build question navigator palette
 const palette = document.getElementById('questionPalette');
 palette.innerHTML = t.questions.map((q, i) => {
 const isAnswered = t.answers[String(q.id)] ? 'answered' : '';
 const isActive = i === t.currentIndex ? 'active' : '';
 return `<button class="test-palette-btn ${isAnswered} ${isActive}" id="pal-btn-${i}" onclick="jumpToQuestion(${i})">${i + 1}</button>`;
 }).join('');

 updateActiveTimerDisplay(t);

 // Resume singleton timer loop
 _activeExamTimerInterval = setInterval(() => {
 if (t.timerMode === 'timed') {
 t.timerSeconds = (t.timerSeconds || 0) - 1;
 t.totalElapsedSeconds = (t.totalElapsedSeconds || 0) + 1;
 updateActiveTimerDisplay(t);

 if (t.timerSeconds <= 0) {
 _stopActiveExamTimer();
 showToast(' Time is up! Submitting your exam automatically...');
 submitTest(true);
 return;
 }
 } else {
 t.timerSeconds = (t.timerSeconds || 0) + 1;
 t.totalElapsedSeconds = t.timerSeconds;
 updateActiveTimerDisplay(t);
 }
 }, 1000);
 t.timerInterval = _activeExamTimerInterval;

 renderCurrentQuestion();
 showToast(` Test resumed! Continuing from Question ${(t.currentIndex || 0) + 1} of ${t.totalQuestions}`);
}

function discardPausedTest() {
 if (!confirm('Are you sure you want to discard this paused test? All progress will be lost.')) {
 return;
 }
 _stopActiveExamTimer();
 _testSessionActive = false;
 S.currentTest = null;
 clearPausedTestStorage();
 showToast('Paused test discarded.');
}

// ─────────────────────────────────────────
// Active Test Taking UI
// ─────────────────────────────────────────
function startTestTakingSession() {
 const t = S.currentTest;
 if (!t) return;

 _stopActiveExamTimer();
 _testSessionActive = true;

 document.getElementById('testTakingContainer').style.display = 'block';
 document.getElementById('testSetup').style.display = 'none';
 document.getElementById('pausedTestCard').style.display = 'none';
 document.getElementById('takingTestType').textContent = t.testType;
 document.getElementById('takingTestTopic').textContent = t.topic;

 const palette = document.getElementById('questionPalette');
 palette.innerHTML = t.questions.map((q, i) =>
 `<button class="test-palette-btn ${i === 0 ? 'active' : ''}" id="pal-btn-${i}" onclick="jumpToQuestion(${i})">${i + 1}</button>`
 ).join('');

 updateActiveTimerDisplay(t);

 _activeExamTimerInterval = setInterval(() => {
 if (t.timerMode === 'timed') {
 t.timerSeconds--;
 t.totalElapsedSeconds = (t.totalElapsedSeconds || 0) + 1;
 updateActiveTimerDisplay(t);

 if (t.timerSeconds <= 0) {
 _stopActiveExamTimer();
 showToast(' Time is up! Submitting your exam automatically...');
 submitTest(true);
 return;
 }
 } else {
 t.timerSeconds++;
 t.totalElapsedSeconds = t.timerSeconds;
 updateActiveTimerDisplay(t);
 }
 }, 1000);
 t.timerInterval = _activeExamTimerInterval;

 savePausedTestToStorage(t);
 renderCurrentQuestion();
}

function cleanOptionDisplay(opt) {
 if (!opt && opt !== 0) return '';
 const raw = String(opt).trim();
 // Strip letter labels: Option A:, Choice A., (A), [A], A), A. 
 let str = raw.replace(/^(?:(?:Option|Choice|Answer)\s+[A-D]\s*[:.)\-]?\s*|\([A-D]\)\s*[:.)\-]?\s*|\[[A-D]\]\s*[:.)\-]?\s*|[A-D]\s*[:.)\-]\s+)/i, '').trim();
 // Strip number prefix ONLY if 1-4 followed by space and text (e.g. "1. 12 layers")
 str = str.replace(/^(?:\([1-4]\)\s*[:.)\-]?\s*|[1-4]\s*[:.)\-]\s+)(?=\S)/, '').trim();
 if (!str || !/[a-zA-Z0-9]/.test(str)) {
 return raw;
 }
 return str;
}

function renderCurrentQuestion() {
 const t = S.currentTest;
 const q = t.questions[t.currentIndex];
 if (!q) return;

 document.getElementById('testProgressFill').style.width =
 `${((t.currentIndex + 1) / t.totalQuestions) * 100}%`;
 document.getElementById('qNumberBadge').textContent =
 `Question ${t.currentIndex + 1} of ${t.totalQuestions}`;

 const chapBadge = document.getElementById('qChapterBadge');
 if (chapBadge) {
 if (q.chapterTitle) {
 chapBadge.textContent = q.chapterTitle + (q.sourcePage ? ` • p.${q.sourcePage}` : '');
 chapBadge.style.display = 'inline-flex';
 } else {
 chapBadge.style.display = 'none';
 }
 }

 const cb = document.getElementById('qCategoryBadge');
 cb.textContent = q.category || '';
 cb.className = 'q-cat-badge ' + getCategoryClass(q.category);
 document.getElementById('qTextDisplay').textContent = q.questionText || q.question || '';

 const selAns = t.answers[String(q.id)];
 const optList = document.getElementById('qOptionsList');
 const options = q.options || [];
 optList.innerHTML = options.map((opt, i) => {
 const isSelected = (selAns === opt) ? 'selected' : '';
 let cleanText = cleanOptionDisplay(opt);
 if (!cleanText || !/[a-zA-Z0-9]/.test(cleanText)) {
 cleanText = String(opt || '').trim();
 if (!cleanText || !/[a-zA-Z0-9]/.test(cleanText)) {
 cleanText = `Option ${String.fromCharCode(65 + i)}`;
 }
 }
 const safeText = cleanText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
 return `
 <div class="q-opt-item ${isSelected}" onclick="selectQuestionOption(${i})">
 <div class="q-opt-letter">${String.fromCharCode(65 + i)}</div>
 <div style="flex:1">${safeText}</div>
 </div>
 `;
 }).join('');

 document.querySelectorAll('.test-palette-btn').forEach((btn, i) => {
 btn.classList.toggle('active', i === t.currentIndex);
 });
 document.getElementById('prevQBtn').disabled = t.currentIndex === 0;
 document.getElementById('nextQBtn').disabled = t.currentIndex === t.totalQuestions - 1;
}

function getCategoryClass(cat) {
 const c = (cat || '').toLowerCase();
 if (c.includes('memory')) return 'cat-memory';
 if (c.includes('logic')) return 'cat-logic';
 if (c.includes('critical')) return 'cat-critical';
 if (c.includes('creative')) return 'cat-creative';
 return 'cat-memory';
}

function selectQuestionOption(optIdx) {
 const t = S.currentTest;
 if (!t) return;
 const q = t.questions[t.currentIndex];
 if (!q || !q.options || q.options[optIdx] === undefined) return;
 t.answers[String(q.id)] = q.options[optIdx];
 const palBtn = document.getElementById(`pal-btn-${t.currentIndex}`);
 if (palBtn) palBtn.classList.add('answered');
 savePausedTestToStorage(t);
 renderCurrentQuestion();
}

function prevQuestion() {
 if (!S.currentTest || S.currentTest.currentIndex <= 0) return;
 S.currentTest.currentIndex--;
 savePausedTestToStorage(S.currentTest);
 renderCurrentQuestion();
}

function nextQuestion() {
 if (!S.currentTest || S.currentTest.currentIndex >= S.currentTest.totalQuestions - 1) return;
 S.currentTest.currentIndex++;
 savePausedTestToStorage(S.currentTest);
 renderCurrentQuestion();
}

function jumpToQuestion(idx) {
 if (!S.currentTest) return;
 S.currentTest.currentIndex = idx;
 savePausedTestToStorage(S.currentTest);
 renderCurrentQuestion();
}

// ─────────────────────────────────────────
// Submit Test & Current Test Report
// ─────────────────────────────────────────
function submitTest(isAutoSubmit = false) {
 const t = S.currentTest;
 if (!t) return;

 if (!isAutoSubmit) {
 const answered = Object.keys(t.answers).length;
 if (answered < t.totalQuestions) {
 if (!confirm(`You've answered ${answered} of ${t.totalQuestions} questions. Submit anyway?`)) return;
 }
 }

 _stopActiveExamTimer();
 _testSessionActive = false;
 clearPausedTestStorage();
 showToast(isAutoSubmit ? ' Time expired! Evaluating test...' : 'Evaluating answers and computing cognitive diagnostics...');

 const timeTaken = t.totalElapsedSeconds || (t.timerMode === 'timed' ? Math.max(1, (t.timeLimitMinutes * 60) - (t.timerSeconds || 0)) : (t.timerSeconds || 0));

 fetch('/submit-test', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 test_id : t.testId,
 student_id : S.studentId,
 topic : t.topic,
 questions : t.questions,
 answers : t.answers,
 time_taken_seconds: timeTaken
 })
 })
 .then(r => r.json())
 .then(report => {
 document.getElementById('testTakingContainer').style.display = 'none';
 renderCurrentTestReport(report);
 loadOverallReports();
 refreshStats();
 setTimeout(() => showToast(' Report automatically saved to the Reports section.'), 600);
 })
 .catch(err => {
 console.error('[SUBMIT ERROR]', err);
 showToast('Failed to submit test. Please try again.');
 });
}

function renderCurrentTestReport(report) {
 const resultsEl = document.getElementById('testResults');
 resultsEl.style.display = 'flex';

 const mins = Math.floor((report.timeTakenSeconds || 0) / 60);
 const secs = (report.timeTakenSeconds || 0) % 60;

 // Category breakdown cards
 const catCards = Object.entries(report.categoryBreakdown || {}).map(([cat, cd]) => `
 <div class="cat-card">
 <div class="cat-card-header">
 <span class="cat-card-title">${cat}</span>
 <span class="cat-card-score" style="color:${cd.color}">${cd.score}/${cd.total} (${cd.percentage}%)</span>
 </div>
 <div class="cat-progress-track">
 <div class="cat-progress-bar" style="width:${cd.percentage}%;background:${cd.color}"></div>
 </div>
 <div class="cat-analysis-text">${cd.analysis}</div>
 </div>
 `).join('');

 // Chapter Mastery Cards
 let chapterBreakdownHtml = '';
 const chapEntries = Object.entries(report.chapterBreakdown || {});
 if (chapEntries.length > 0) {
 const chapCards = chapEntries.map(([chap, cd]) => {
 const color = cd.percentage >= 75 ? 'var(--success)' : (cd.percentage >= 50 ? 'var(--warning)' : 'var(--danger)');
 return `
 <div class="chapter-mastery-card">
 <div class="chapter-mastery-title" title="${chap}"><i class="bi bi-book"></i> ${chap}</div>
 <div class="chapter-mastery-stat">
 <span>${cd.score}/${cd.total} Correct</span>
 <span style="color:${color}">${cd.percentage}%</span>
 </div>
 <div class="chapter-mastery-bar">
 <div class="chapter-mastery-fill" style="width:${cd.percentage}%;background:${color}"></div>
 </div>
 </div>
 `;
 }).join('');

 chapterBreakdownHtml = `
 <div style="margin-top:16px">
 <h3 style="font-size:1.05rem;font-weight:800;margin-bottom:10px">
 <i class="bi bi-book-half" style="color:var(--primary)"></i> Chapter &amp; Section Mastery
 </h3>
 <div class="chapter-mastery-grid">${chapCards}</div>
 </div>
 `;
 }

 let actionBanner = '';
 const ra = report.recommendedAction;
 if (ra && ra.type === 'schedule_plan') {
 actionBanner = `
 <div class="action-banner-card">
 <div class="action-banner-text">
 <i class="bi bi-lightbulb-fill" style="color:var(--warning);margin-right:6px"></i>
 ${ra.message}
 </div>
 <button class="btn-primary" onclick="schedulePlanForWeakArea(${JSON.stringify(ra.topic)}, ${ra.suggestedDurationMins})">
 <i class="bi bi-calendar-plus"></i> Schedule Review
 </button>
 </div>
 `;
 }

  const delta = report.pointsDelta !== undefined ? report.pointsDelta : ((report.totalCorrect * 20) - ((report.totalQuestions - report.totalCorrect) * 10));
  const deltaBadge = delta > 0
    ? `<span style="color:#10b981;font-weight:700"><i class="bi bi-arrow-up-circle-fill"></i> +${delta} pts</span>`
    : delta < 0
    ? `<span style="color:#ef4444;font-weight:700"><i class="bi bi-arrow-down-circle-fill"></i> ${delta} pts</span>`
    : `<span style="color:#6b7280;font-weight:700"><i class="bi bi-dash-circle-fill"></i> 0 pts</span>`;

  // Question reviews
  const reviews = (report.questionReviews || []).map(q => {
    const optsJson = JSON.stringify(q.options || []).replace(/"/g, '&quot;');
    const qTextEsc = (q.questionText || '').replace(/"/g, '&quot;');
    const correctEsc = (q.correctAnswer || '').replace(/"/g, '&quot;');
    const userEsc = (q.userAnswer || '').replace(/"/g, '&quot;');
    const topicEsc = (report.topic || '').replace(/"/g, '&quot;');
    const catEsc = (q.category || '').replace(/"/g, '&quot;');
    const chapBadge = q.chapterTitle ? `<span class="chapter-page-badge" style="margin-left:6px"><i class="bi bi-book"></i> ${q.chapterTitle}${q.sourcePage ? ' • p.' + q.sourcePage : ''}</span>` : '';

    return `
      <div class="review-q-item ${q.isCorrect ? 'is-correct' : 'is-wrong'}" id="review-q-${q.id}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;gap:8px">
          <span style="font-weight:700;font-size:0.85rem;flex:1">Q${q.id}. <span style="color:var(--muted);font-weight:500">[${q.category}]</span> ${chapBadge}</span>
          <span style="font-weight:800;color:${q.isCorrect ? 'var(--success)' : 'var(--danger)'};flex-shrink:0">
            ${q.isCorrect ? ' Correct' : ' Incorrect'}
          </span>
        </div>
        <div style="font-weight:600;margin-bottom:8px;line-height:1.4">${q.questionText}</div>
        <div style="font-size:0.82rem;display:flex;flex-wrap:gap:12px;margin-bottom:8px">
          <span><b>Your Answer:</b> <span style="color:${q.isCorrect ? 'var(--success)' : 'var(--danger)'}">${q.userAnswer || '—'}</span></span>
          ${!q.isCorrect ? `<span style="color:var(--success)"><b>Correct:</b> ${q.correctAnswer}</span>` : ''}
        </div>
        <div id="exp-box-${q.id}" style="display:none" class="review-exp-box"></div>
        <button class="explain-btn"
          id="exp-btn-${q.id}"
          data-qid="${q.id}"
          data-qtext="${qTextEsc}"
          data-options="${optsJson}"
          data-correct="${correctEsc}"
          data-user="${userEsc}"
          data-category="${catEsc}"
          data-topic="${topicEsc}"
          onclick="requestExplanation(this)">
          <i class="bi bi-lightbulb"></i> Explain This
        </button>
      </div>
    `;
  }).join('');

  resultsEl.innerHTML = `
    <div class="report-score-hero">
      <div class="score-circle-wrap" style="--pct:${report.percentage}">
        <div class="score-circle-inner">
          <div class="score-circle-num">${Math.round(report.percentage)}%</div>
          <div class="score-circle-label">Score</div>
        </div>
      </div>
      <div class="report-hero-details">
        <div class="grade-badge" style="background:${report.badgeColor}">${report.grade}</div>
        <div class="report-headline-text">${report.topic}</div>
        <div class="report-sub-meta">
          <span><i class="bi bi-check2-circle"></i> ${report.totalCorrect}/${report.totalQuestions}</span>
          <span><i class="bi bi-stopwatch"></i> ${mins}m ${secs}s</span>
          ${deltaBadge}
        </div>
        <div class="saved-badge"><i class="bi bi-check-circle-fill"></i> Saved to Reports</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;flex-shrink:0">
        <button class="btn-outline" onclick="resetTest()"><i class="bi bi-arrow-repeat"></i> New Test</button>
        <button class="btn-primary" onclick="setView('reports')"><i class="bi bi-bar-chart-fill"></i> View Reports</button>
      </div>
    </div>
    ${actionBanner}
    <div>
      <h3 style="font-size:1.05rem;font-weight:800;margin-bottom:12px">
        <i class="bi bi-diagram-3-fill" style="color:var(--primary)"></i> Cognitive Domain Breakdown
      </h3>
      <div class="category-breakdowns-grid">${catCards}</div>
    </div>
    ${chapterBreakdownHtml}
    <div class="review-section">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px">
        <h3 style="font-size:1.05rem;font-weight:800;margin:0">
          <i class="bi bi-card-checklist" style="color:var(--primary)"></i> Question-by-Question Review
        </h3>
        <span class="hint"><i class="bi bi-lightbulb"></i> Click "Explain This" to generate a focused AI explanation</span>
      </div>
      ${reviews}
    </div>
  `;
}
// Global in memory cache for on demand explanations
const _explanationCache = {};

/**
 * Generates or reveals a focused AI explanation strictly on demand.
 */
function requestExplanation(btn) {
 const qId = btn.dataset.qid;
 const qText = btn.dataset.qtext;
 let options = [];
 try { options = JSON.parse(btn.dataset.options || '[]'); } catch (e) {}
 const correctAnswer = btn.dataset.correct;
 const userAnswer = btn.dataset.user;
 const category = btn.dataset.category;
 const topic = btn.dataset.topic;

 const expBox = document.getElementById(`exp-box-${qId}`);
 if (!expBox) return;

 const cacheKey = `${topic}-${qId}`;

 // If already visible, toggle it closed
 if (expBox.style.display === 'block') {
 expBox.style.display = 'none';
 btn.innerHTML = '<i class="bi bi-lightbulb"></i> Explain This';
 return;
 }

 // If cached, show instantly
 if (_explanationCache[cacheKey]) {
 expBox.innerHTML = `<b>AI Explanation:</b> ${_explanationCache[cacheKey]}`;
 expBox.style.display = 'block';
 btn.innerHTML = '<i class="bi bi-lightbulb-fill"></i> Hide Explanation';
 return;
 }

 // Fetch live on demand
 expBox.style.display = 'block';
 expBox.innerHTML = `
 <div style="display:flex;align-items:center;gap:8px;color:var(--muted);font-size:0.8rem;padding:4px 0">
 <div class="spinner" style="width:14px;height:14px;border-width:2px"></div>
 <span>Generating AI explanation with ${S.modelConfig.qa || 'mistral'}…</span>
 </div>
 `;
 btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Generating…';
 btn.disabled = true;

 const model = S.modelConfig.qa || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Q&A';
 updateActiveModelBar();

 fetch('/explain-question', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 questionText: qText,
 options,
 correctAnswer,
 userAnswer,
 category,
 topic,
 model
 })
 })
 .then(r => r.json())
 .then(data => {
 btn.disabled = false;
 const explanation = data.explanation || `The correct answer is "${correctAnswer}".`;
 _explanationCache[cacheKey] = explanation;
 expBox.innerHTML = `<b>AI Explanation:</b> ${explanation}`;
 btn.innerHTML = '<i class="bi bi-lightbulb-fill"></i> Hide Explanation';
 })
 .catch(err => {
 btn.disabled = false;
 btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Retry Explanation';
 expBox.innerHTML = `<span style="color:var(--danger)">Could not generate explanation. Make sure Ollama is active.</span>`;
 });
}


function resetTest() {
 _stopActiveExamTimer();
 _testSessionActive = false;
 S.currentTest = null;
 clearPausedTestStorage();
 const tv = document.getElementById('view-test');
 if (tv && tv.classList.contains('fullscreen-test-mode')) {
 toggleTestFullscreen();
 }
 document.getElementById('testSetup').style.display = 'block';
 document.getElementById('testTakingContainer').style.display = 'none';
 document.getElementById('testResults').style.display = 'none';
 document.getElementById('testLoading').style.display = 'none';
 populateTestDocSelect();
}

// ─────────────────────────────────────────
// Overall Reports & Charts
// ─────────────────────────────────────────
function loadOverallReports() {
 fetch(`/reports/overall?student_id=${S.studentId}`)
 .then(r => r.json())
 .then(data => {
  // 1. Knowledge Points / Tier
  const kp = data.knowledgePoints;
  if (kp) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('kpScore', `${kp.points} pts`);

    const tierIcons = {
      'Novice': '<i class="bi bi-shield"></i>',
      'Apprentice': '<i class="bi bi-mortarboard"></i>',
      'Practitioner': '<i class="bi bi-book"></i>',
      'Scholar': '<i class="bi bi-patch-check-fill"></i>',
      'Master': '<i class="bi bi-award-fill"></i>',
      'Grandmaster': '<i class="bi bi-trophy-fill"></i>',
      'Beginner': '<i class="bi bi-shield"></i>',
      'Intermediate': '<i class="bi bi-book"></i>',
      'Expert': '<i class="bi bi-trophy-fill"></i>'
    };
    const tIcon = tierIcons[kp.tier] || '<i class="bi bi-award-fill"></i>';
    const tierEl = document.getElementById('kpTier');
    if (tierEl) tierEl.innerHTML = `${tIcon} ${kp.tier}`;

    const nextTierName = kp.tier === 'Novice' ? 'Apprentice'
      : kp.tier === 'Apprentice' ? 'Practitioner'
      : kp.tier === 'Practitioner' ? 'Scholar'
      : kp.tier === 'Scholar' ? 'Master'
      : kp.tier === 'Master' ? 'Grandmaster'
      : 'Max Tier';

    set('kpLabel', kp.tier === 'Grandmaster' || kp.tier === 'Expert'
      ? 'Maximum mastery tier achieved!'
      : `${kp.points} / ${kp.nextTierPoints} pts → Next: ${nextTierName}`);
    set('kpTotalCorrect', kp.totalCorrect || 0);
    set('kpTestsDone', kp.testsCompleted || 0);
    const bar = document.getElementById('kpBar');
    if (bar) bar.style.width = `${kp.progressPct || 0}%`;
    const tb = document.getElementById('tierBadgeLarge');
    if (tb) tb.innerHTML = `${tIcon} ${kp.tier}`;

    // Update liveDocs doc count
    fetch('/documents').then(r => r.json()).then(d => {
      const ld = document.getElementById('liveDocs');
      if (ld) ld.textContent = `${(d.documents || []).length} docs`;
    }).catch(() => {});
  }

 // 2. Forgetting Curve
 const fc = data.forgettingCurve;
 if (fc) {
 const retScore = document.getElementById('currentRetentionPct');
 const retDesc = document.getElementById('retentionDesc');
 if (retScore) retScore.textContent = `${fc.currentRetention}%`;
 if (retDesc) retDesc.textContent = fc.needsReview
 ? ` Retention on "${fc.topic}" dropped below 60% (${fc.daysSinceTest} days ago). Review recommended!`
 : ` Strong memory on "${fc.topic}". Estimated retention: ${fc.currentRetention}%.`;
 renderForgettingCurveChart(fc.curveData || []);
 }

 // 3. Category Radar
 renderCategoryRadarChart(data.categoryPerformance || {});

 // 4. Score Trend
 renderScoreTrendChart(data.history || []);

 // 5. History Table
 renderTestHistoryTable(data.history || []);

 // 6. Weak Areas
 refreshWeakAreas();
 })
 .catch(err => console.warn('[Reports] Load error:', err));
}

function renderForgettingCurveChart(curveData) {
 const ctx = document.getElementById('forgettingCurveChart')?.getContext('2d');
 if (!ctx) return;
 if (forgettingChartInst) { forgettingChartInst.destroy(); forgettingChartInst = null; }
 if (!curveData || !curveData.length) return;

 forgettingChartInst = new Chart(ctx, {
 type: 'line',
 data: {
 labels : curveData.map(d => d.day),
 datasets: [{
 label : 'Retention %',
 data : curveData.map(d => d.retention),
 borderColor : '#4361ee',
 backgroundColor: 'rgba(67,97,238,0.1)',
 fill : true,
 tension : 0.35,
 pointRadius : 3
 }]
 },
 options: {
 responsive: true, maintainAspectRatio: false,
 plugins: { legend: { display: false } },
 scales: {
 y: { min: 0, max: 100, ticks: { font: { size: 9 } } },
 x: { ticks: { font: { size: 9 } } }
 }
 }
 });
}

function renderCategoryRadarChart(catPerf) {
 const ctx = document.getElementById('categoryRadarChart')?.getContext('2d');
 if (!ctx) return;
 if (radarChartInst) { radarChartInst.destroy(); radarChartInst = null; }

 const labels = ['Cognitive Memory', 'Logical Reasoning', 'Critical Thinking', 'Creative Application'];
 const values = labels.map(l => catPerf[l]?.percentage || 0);

 radarChartInst = new Chart(ctx, {
 type: 'radar',
 data: {
 labels : ['Memory', 'Logic', 'Critical', 'Creative'],
 datasets: [{
 label : 'Mastery %',
 data : values,
 backgroundColor : 'rgba(67,97,238,0.2)',
 borderColor : '#4361ee',
 pointBackgroundColor: '#3f37c9'
 }]
 },
 options: {
 responsive: true, maintainAspectRatio: false,
 scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, font: { size: 8 } } } },
 plugins: { legend: { display: false } }
 }
 });
}

function renderScoreTrendChart(history) {
 const ctx = document.getElementById('scoreTrendChart')?.getContext('2d');
 if (!ctx) return;
 if (trendChartInst) { trendChartInst.destroy(); trendChartInst = null; }

 const sorted = [...history].reverse();
 trendChartInst = new Chart(ctx, {
 type: 'line',
 data: {
 labels : sorted.length ? sorted.map((_, i) => `Test ${i + 1}`) : ['No tests yet'],
 datasets: [{
 label : 'Score %',
 data : sorted.length ? sorted.map(h => h.percentage) : [0],
 borderColor : '#23b26d',
 backgroundColor: 'rgba(35,178,109,0.1)',
 fill : true,
 tension : 0.3,
 pointRadius : 4,
 pointBackgroundColor: '#23b26d'
 }]
 },
 options: {
 responsive: true, maintainAspectRatio: false,
 plugins: { legend: { display: false } },
 scales: {
 y: { min: 0, max: 100, ticks: { font: { size: 9 } } },
 x: { ticks: { font: { size: 9 } } }
 }
 }
 });
}

function renderTestHistoryTable(history) {
 const wrap = document.getElementById('testHistory');
 if (!wrap) return;
 if (!history.length) {
 wrap.innerHTML = '<div class="empty-msg">No tests taken yet. Generate your first test above!</div>';
 return;
 }
 wrap.innerHTML = `
 <table class="history-table">
 <thead>
 <tr><th>Date</th><th>Topic</th><th>Score</th><th>%</th><th>Duration</th><th>Action</th></tr>
 </thead>
 <tbody>
 ${history.map(h => {
 const dt = new Date(h.createdAt || h.timestamp).toLocaleDateString();
 const mins = Math.floor((h.timeTakenSeconds || 0) / 60);
 const secs = (h.timeTakenSeconds || 0) % 60;
 const pct = Math.round(h.percentage || 0);
 const col = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--danger)';
 return `
 <tr>
 <td>${dt}</td>
 <td><b>${h.topic}</b></td>
 <td>${h.totalScore}/${h.totalPossible}</td>
 <td><b style="color:${col}">${pct}%</b></td>
 <td>${mins}m ${secs}s</td>
 <td>
 <button class="history-btn-inspect" onclick="inspectHistoricalReport('${h.testId}')">
 <i class="bi bi-eye"></i> View
 </button>
 </td>
 </tr>
 `;
 }).join('')}
 </tbody>
 </table>
 `;
}

function inspectHistoricalReport(testId) {
 fetch(`/reports/current/${testId}`)
 .then(r => r.json())
 .then(report => {
 const modal = document.getElementById('diagnosticModal');
 const body = document.getElementById('diagModalBody');
 const sub = document.getElementById('diagModalSub');
 if (sub) sub.textContent = `${report.topic} — ${new Date(report.timestamp).toLocaleString()}`;

 body.innerHTML = `
 <div class="current-report-container">
 <div class="report-score-hero" style="margin-bottom:14px">
 <div class="score-circle-wrap" style="--pct:${report.percentage}">
 <div class="score-circle-inner">
 <div class="score-circle-num">${Math.round(report.percentage)}%</div>
 <div class="score-circle-label">Score</div>
 </div>
 </div>
 <div class="report-hero-details">
 <div class="grade-badge" style="background:${report.badgeColor}">${report.grade}</div>
 <div class="report-headline-text">${report.topic}</div>
 <div class="report-sub-meta">
 <span>${report.totalCorrect}/${report.totalQuestions} correct</span>
 </div>
 </div>
 </div>
 <div class="category-breakdowns-grid">
 ${Object.entries(report.categoryBreakdown || {}).map(([cat, cd]) => `
 <div class="cat-card">
 <div class="cat-card-header">
 <span class="cat-card-title">${cat}</span>
 <span class="cat-card-score" style="color:${cd.color}">${cd.score}/${cd.total} (${cd.percentage}%)</span>
 </div>
 <div class="cat-progress-track">
 <div class="cat-progress-bar" style="width:${cd.percentage}%;background:${cd.color}"></div>
 </div>
 <div class="cat-analysis-text">${cd.analysis}</div>
 </div>
 `).join('')}
 </div>
 <div class="review-section" style="margin-top:14px">
 <h4 style="font-weight:800;margin-bottom:10px">Question Review</h4>
 ${(report.questionReviews || []).map(q => {
 const optsJson = JSON.stringify(q.options || []).replace(/"/g, '&quot;');
 const qTextEsc = (q.questionText || '').replace(/"/g, '&quot;');
 const correctEsc = (q.correctAnswer || '').replace(/"/g, '&quot;');
 const userEsc = (q.userAnswer || '').replace(/"/g, '&quot;');
 const topicEsc = (report.topic || '').replace(/"/g, '&quot;');
 const catEsc = (q.category || '').replace(/"/g, '&quot;');
 return `
 <div class="review-q-item ${q.isCorrect ? 'is-correct' : 'is-wrong'}">
 <div style="font-weight:700;margin-bottom:4px">Q${q.id}. ${q.questionText}</div>
 <div style="font-size:0.8rem;margin-bottom:6px">
 <b>Your Answer:</b>
 <span style="color:${q.isCorrect ? 'var(--success)' : 'var(--danger)'}">${q.userAnswer || '—'}</span>
 ${!q.isCorrect ? ` | <b>Correct:</b> <span style="color:var(--success)">${q.correctAnswer}</span>` : ''}
 </div>
 <div id="exp-box-hist-${q.id}" style="display:none" class="review-exp-box"></div>
 <button class="explain-btn"
 id="exp-btn-hist-${q.id}"
 data-qid="hist-${q.id}"
 data-qtext="${qTextEsc}"
 data-options="${optsJson}"
 data-correct="${correctEsc}"
 data-user="${userEsc}"
 data-category="${catEsc}"
 data-topic="${topicEsc}"
 onclick="requestExplanation(this)">
 <i class="bi bi-lightbulb"></i> Explain This
 </button>
 </div>
 `;
 }).join('')}
 </div>
 </div>
 `;
 modal.style.display = 'flex';
 })
 .catch(() => showToast('Could not load historical report.'));
}

function closeDiagnosticModal() {
  const m = document.getElementById('diagnosticModal');
  if (m) m.style.display = 'none';
}

function openOverallDiagnosticModal() {
  const modal = document.getElementById('overallDiagnosticModal');
  const body = document.getElementById('overallDiagModalBody');
  const sub = document.getElementById('overallDiagModalSub');
  if (!modal || !body) return;

  modal.style.display = 'flex';
  body.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;text-align:center">
      <div class="spinner-sm" style="width:36px;height:36px;margin-bottom:14px"></div>
      <div style="font-weight:700;color:var(--text);font-size:1rem">Synthesizing Overall Cognitive Diagnostics...</div>
      <div style="font-size:0.82rem;color:var(--muted);margin-top:4px">Aggregating test history, mastery points, and cognitive domain curves</div>
    </div>
  `;

  fetch(`/reports/overall/diagnostic?student_id=${S.studentId}`)
    .then(r => r.json())
    .then(rep => {
      if (sub) sub.textContent = `Cumulative cognitive mastery across all ${rep.totalTests} completed tests`;

      if (!rep || rep.totalTests === 0) {
        body.innerHTML = `
          <div style="text-align:center;padding:40px 20px;background:white;border-radius:14px;border:1px solid #e2e8f0">
            <div style="font-size:2.5rem;color:var(--muted);margin-bottom:12px"><i class="bi bi-journal-x"></i></div>
            <h4 style="font-weight:800;margin-bottom:6px">No Tests Completed Yet</h4>
            <p style="color:var(--muted);font-size:0.85rem;max-width:420px;margin:0 auto 16px auto">
              Take your first MCQ practice test from any uploaded document or study note to unlock full cognitive domain diagnostic analysis and personalized improvement strategies.
            </p>
            <button class="btn-primary" onclick="closeOverallDiagnosticModal();setView('test')">
              <i class="bi bi-pencil-square"></i> Generate Practice Test Now
            </button>
          </div>
        `;
        return;
      }

      // 4 Cognitive Category Cards
      const catCards = Object.entries(rep.categoryBreakdown || {}).map(([cat, cd]) => {
        const tipsList = (cd.tips || []).map(t => `<li>${escapeHtml(t)}</li>`).join('');
        const statusBadge = cd.percentage >= 80
          ? `<span style="background:#ecfdf5;color:#059669;font-size:0.7rem;font-weight:800;padding:2px 8px;border-radius:10px">Strong Mastery</span>`
          : cd.percentage >= 60
          ? `<span style="background:#eff6ff;color:#2563eb;font-size:0.7rem;font-weight:800;padding:2px 8px;border-radius:10px">Developing</span>`
          : `<span style="background:#fef2f2;color:#dc2626;font-size:0.7rem;font-weight:800;padding:2px 8px;border-radius:10px">Critical Weak Area</span>`;

        return `
          <div class="cat-card" style="display:flex;flex-direction:column;justify-content:space-between">
            <div>
              <div class="cat-card-header" style="align-items:center;margin-bottom:8px">
                <div style="display:flex;align-items:center;gap:6px">
                  <span class="cat-card-title" style="font-size:0.92rem;font-weight:800">${cat}</span>
                  ${statusBadge}
                </div>
                <span class="cat-card-score" style="color:${cd.color};font-weight:800;font-size:0.92rem">${cd.score}/${cd.total} (${cd.percentage}%)</span>
              </div>
              <div class="cat-progress-track" style="margin-bottom:10px;height:8px;border-radius:4px">
                <div class="cat-progress-bar" style="width:${cd.percentage}%;background:${cd.color};border-radius:4px"></div>
              </div>
              <div class="cat-analysis-text" style="font-size:0.82rem;line-height:1.45;color:#334155;margin-bottom:10px">${escapeHtml(cd.analysis)}</div>
            </div>
            ${cd.tips && cd.tips.length ? `
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin-top:6px">
                <div style="font-size:0.72rem;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">
                  <i class="bi bi-lightbulb-fill" style="color:var(--warning)"></i> Recommended Study Techniques:
                </div>
                <ul style="margin:0;padding-left:18px;font-size:0.76rem;color:#1e293b;line-height:1.4">
                  ${tipsList}
                </ul>
              </div>
            ` : ''}
          </div>
        `;
      }).join('');

      // Personalized Pedagogical Weak-Area Action Banner
      let actionBannerHtml = '';
      if (rep.recommendedAction && rep.recommendedAction.type === 'schedule_plan') {
        const ra = rep.recommendedAction;
        actionBannerHtml = `
          <div class="action-banner-card" style="background:linear-gradient(135deg, #eff6ff, #dbeafe);border:1.5px solid #bfdbfe;padding:16px 18px;border-radius:12px;margin-bottom:18px">
            <div style="display:flex;align-items:flex-start;gap:12px;flex:1">
              <div style="width:36px;height:36px;border-radius:10px;background:#3b82f6;color:white;display:flex;align-items:center;justify-content:center;font-size:1.2rem;flex-shrink:0">
                <i class="bi bi-bullseye"></i>
              </div>
              <div>
                <div style="font-size:0.95rem;font-weight:800;color:#1e3a8a;margin-bottom:3px">Targeted Weak-Area Remedial Strategy</div>
                <div style="font-size:0.83rem;color:#1e40af;line-height:1.45">${escapeHtml(ra.message)}</div>
              </div>
            </div>
            <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
              <button class="btn-primary" onclick="closeOverallDiagnosticModal();schedulePlanForWeakArea(${JSON.stringify(ra.topic)}, ${ra.suggestedDurationMins || 30})" style="padding:8px 14px;font-size:0.8rem">
                <i class="bi bi-calendar-plus"></i> Schedule Remedial Session (${ra.suggestedDurationMins}m)
              </button>
              <button class="btn-outline" onclick="closeOverallDiagnosticModal();launchRemedialQuiz(${JSON.stringify(ra.topic)})" style="padding:8px 14px;font-size:0.8rem;background:white">
                <i class="bi bi-play-circle-fill"></i> Launch Remedial Quiz
              </button>
            </div>
          </div>
        `;
      }

      // Step-by-Step AI Improvement Roadmap
      const roadmapItems = (rep.actionPlan || []).map((step, idx) => `
        <div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:8px">
          <div style="width:22px;height:22px;border-radius:50%;background:#e0e7ff;color:#4361ee;font-weight:800;font-size:0.75rem;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px">
            ${idx + 1}
          </div>
          <div style="font-size:0.83rem;color:#1e293b;line-height:1.45">
            ${step.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')}
          </div>
        </div>
      `).join('');

      body.innerHTML = `
        <div class="current-report-container" style="display:flex;flex-direction:column;gap:16px">
          <!-- Overall Hero -->
          <div class="report-score-hero" style="background:white;border:1px solid #e2e8f0;border-radius:14px;padding:20px;box-shadow:0 4px 16px rgba(0,0,0,0.03)">
            <div class="score-circle-wrap" style="--pct:${rep.overallPercentage}">
              <div class="score-circle-inner">
                <div class="score-circle-num">${Math.round(rep.overallPercentage)}%</div>
                <div class="score-circle-label">Cumulative</div>
              </div>
            </div>
            <div class="report-hero-details" style="flex:1">
              <div class="grade-badge" style="background:${rep.badgeColor}">${rep.grade}</div>
              <div class="report-headline-text" style="font-size:1.15rem;font-weight:800;color:var(--text)">All Attempted Tests Cumulative Analytics</div>
              <div class="report-sub-meta" style="display:flex;flex-wrap:wrap;gap:12px;margin-top:6px;font-size:0.82rem;color:var(--muted)">
                <span><i class="bi bi-check2-circle" style="color:var(--success)"></i> <b>${rep.totalCorrect}/${rep.totalQuestions}</b> Total Correct</span>
                <span><i class="bi bi-file-earmark-check" style="color:var(--primary)"></i> <b>${rep.totalTests}</b> Tests Taken</span>
                <span><i class="bi bi-patch-check-fill" style="color:#059669"></i> <b>${rep.testsPassed}</b> Passed (${Math.round((rep.testsPassed / rep.totalTests) * 100)}%)</span>
                <span><i class="bi bi-award-fill" style="color:#f59e0b"></i> <b>${rep.knowledgePoints?.tier || 'Novice'}</b> (${rep.knowledgePoints?.points || 0} pts)</span>
              </div>
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;flex-shrink:0">
              <button class="btn-outline" onclick="window.print()" style="font-size:0.8rem;padding:7px 12px">
                <i class="bi bi-printer"></i> Print Report
              </button>
            </div>
          </div>

          ${actionBannerHtml}

          <!-- 4 Cognitive Categories -->
          <div>
            <h4 style="font-size:0.98rem;font-weight:800;margin-bottom:12px;display:flex;align-items:center;gap:6px">
              <i class="bi bi-diagram-3-fill" style="color:var(--primary)"></i> Cumulative Cognitive Domain Mastery
            </h4>
            <div class="category-breakdowns-grid">
              ${catCards}
            </div>
          </div>

          <!-- Improvement Strategy Roadmap -->
          <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px">
            <h4 style="font-size:0.95rem;font-weight:800;margin-bottom:12px;display:flex;align-items:center;gap:6px;color:#0f172a">
              <i class="bi bi-compass-fill" style="color:var(--primary)"></i> Pedagogical Weak-Area Improvement Roadmap
            </h4>
            <div style="display:flex;flex-direction:column">
              ${roadmapItems}
            </div>
          </div>
        </div>
      `;
    })
    .catch(err => {
      body.innerHTML = `
        <div style="text-align:center;padding:30px;color:var(--danger)">
          <i class="bi bi-exclamation-triangle" style="font-size:2rem"></i>
          <div style="margin-top:8px;font-weight:700">Failed loading overall diagnostic report.</div>
        </div>
      `;
    });
}

function closeOverallDiagnosticModal() {
  const m = document.getElementById('overallDiagnosticModal');
  if (m) m.style.display = 'none';
}

function launchRemedialQuiz(topic) {
  setView('test');
  const tSelect = document.getElementById('testDocSelect');
  if (tSelect && topic) {
    for (let opt of tSelect.options) {
      if (opt.text.toLowerCase().includes(topic.toLowerCase())) {
        tSelect.value = opt.value;
        break;
      }
    }
  }
  showToast(`🎯 Remedial Quiz Mode: Ready to practice "${topic}"`);
}

// ─────────────────────────────────────────
// Interlinking Actions
// ─────────────────────────────────────────
function schedulePlanForWeakArea(topic, durationMins) {
 setView('planner');
 const tI = document.getElementById('planTopic');
 const dI = document.getElementById('planDuration');
 const dtI= document.getElementById('planDateTime');
 const nI = document.getElementById('planNotes');
 if (tI) tI.value = topic;
 if (dI) dI.value = durationMins || 30;
 const tomorrow = new Date();
 tomorrow.setDate(tomorrow.getDate() + 1);
 tomorrow.setHours(10, 0, 0, 0);
 if (dtI) dtI.value = tomorrow.toISOString().slice(0, 16);
 if (nI) nI.value = `Weak-area review session: focus on improving ${topic}.`;
 showToast(' Plan pre-filled! Click "Schedule Session" to save.');
}

function promptPostSessionTest(topic) {
 const liveStats = document.getElementById('liveStats');
 if (!liveStats) return;
 // Remove previous prompt if any
 const existing = document.getElementById('postSessionTestPrompt');
 if (existing) existing.remove();

 const div = document.createElement('div');
 div.id = 'postSessionTestPrompt';
 div.className = 'action-banner-card';
 div.style.marginTop = '10px';
 div.innerHTML = `
 <div style="font-size:0.8rem;font-weight:700"> Test retention now:</div>
 <button class="btn-primary" style="padding:5px 12px;font-size:0.75rem"
 onclick="setView('test');document.getElementById('postSessionTestPrompt').remove()">
 Quick Test
 </button>
 `;
 liveStats.appendChild(div);
 showToast(` Pomodoro complete! Test your retention on "${topic}"?`);
}

// ─────────────────────────────────────────
// Weak Areas & AI Diagnostic Report
// ─────────────────────────────────────────
function refreshWeakAreas() {
 if (!S.studentId) return;
 fetch(`/stats?student_id=${S.studentId}&session_id=${S.sessionId || 0}`)
 .then(r => r.json())
 .then(data => {
 const areas = data.weak_areas || [];
 const el = document.getElementById('weakAreasList');
 if (!el) return;
 el.innerHTML = areas.length
 ? areas.map(a => `
 <div class="weak-item">
 <span>${a.topic}</span>
 <span class="weak-cnt">${a.query_count} queries</span>
 </div>`).join('')
 : '<div class="empty-msg">No weak areas detected yet.</div>';
 })
 .catch(() => {});
}

function generateReport() {
 const el = document.getElementById('aiReport');
 if (!el) return;
 el.style.display = 'block';

 const model = S.modelConfig.analytics || 'llama3';
 S.activeModelName = model;
 S.activeModelTask = 'Analytics';
 updateActiveModelBar();

 el.innerHTML = `<div class="studio-loading"><div class="spinner"></div> <span>Generating AI diagnostic with ${model}...</span></div>`;
 fetch(`/report?student_id=${S.studentId}&model=${model}`)
 .then(r => r.json())
 .then(data => {
 el.innerHTML = `<p style="line-height:1.6;white-space:pre-wrap">${data.report || 'No report generated.'}</p>`;
 })
 .catch(() => { el.innerHTML = 'Error generating report. Make sure Ollama is running.'; });
}

// ─────────────────────────────────────────
// Retrieval-Augmented Study Chat Engine & Workspace
// ─────────────────────────────────────────
let currentChatThreadId = null;
let chatThreadsList = [];

function escapeHtml(text) {
 if (!text) return '';
 return String(text)
 .replace(/&/g, '&amp;')
 .replace(/</g, '&lt;')
 .replace(/>/g, '&gt;')
 .replace(/"/g, '&quot;')
 .replace(/'/g, '&#039;');
}

function escHtml(text) {
 if (text === null || text === undefined) return '';
 return String(text)
 .replace(/&/g, '&amp;')
 .replace(/</g, '&lt;')
 .replace(/>/g, '&gt;')
 .replace(/"/g, '&quot;');
}

function inlineMd(text) {
 if (!text) return '';
 let h = escHtml(text);
 // Bold **text** or __text__
 h = h.replace(/\*\*([^*<]+)\*\*/g, '<strong>$1</strong>');
 h = h.replace(/__([^_<]+)__/g, '<strong>$1</strong>');
 // Italic *text* (avoid ** already replaced)
 h = h.replace(/(?<!\*)\*([^*<\n]+)\*(?!\*)/g, '<em>$1</em>');
 // Inline code `code`
 h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
 return h;
}

function renderMarkdownToHtml(text) {
 if (!text) return '';

 const lines = text.split('\n');
 let html = '';
 let i = 0;

 while (i < lines.length) {
 const raw = lines[i];
 const trimmed = raw.trim();

 // ── Triple backtick code block ──
 if (trimmed.startsWith('```')) {
 const lang = trimmed.slice(3).trim() || 'code';
 const displayLang = lang.toUpperCase();
 const codeLines = [];
 i++;
 while (i < lines.length && !lines[i].trim().startsWith('```')) {
 codeLines.push(lines[i]);
 i++;
 }
 i++; // skip closing ```
 const code = escHtml(codeLines.join('\n'));
 html += `<div class="code-block-wrap">
 <div class="code-header-bar">
 <span class="code-lang-tag">${escHtml(displayLang)}</span>
 <button class="copy-code-btn" onclick="copyCodeBlock(this)">
 <i class="bi bi-clipboard"></i> Copy
 </button>
 </div>
 <pre><code class="language-${escHtml(lang)}">${code}</code></pre>
 </div>`;
 continue;
 }

 // ── Headings ──
 if (trimmed.startsWith('### ')) { html += `<h4>${inlineMd(raw.replace(/^#+\s*/, ''))}</h4>`; i++; continue; }
 if (trimmed.startsWith('## ')) { html += `<h3>${inlineMd(raw.replace(/^#+\s*/, ''))}</h3>`; i++; continue; }
 if (trimmed.startsWith('# ')) { html += `<h2>${inlineMd(raw.replace(/^#+\s*/, ''))}</h2>`; i++; continue; }

 // ── Unordered list ──
 if (/^\s*[-*]\s+/.test(raw)) {
 html += '<ul>';
 while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
 html += `<li>${inlineMd(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`;
 i++;
 }
 html += '</ul>';
 continue;
 }

 // ── Ordered list ──
 if (/^\s*\d+[.)]\s+/.test(raw)) {
 html += '<ol>';
 while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
 html += `<li>${inlineMd(lines[i].replace(/^\s*\d+[.)]\s+/, ''))}</li>`;
 i++;
 }
 html += '</ol>';
 continue;
 }

 // ── Horizontal rule ──
 if (/^[-*_]{3,}$/.test(trimmed)) { html += '<hr>'; i++; continue; }

 // ── Empty line → paragraph spacer ──
 if (trimmed === '') { html += '<div class="para-spacer"></div>'; i++; continue; }

 // ── Regular paragraph line ──
 html += `<p>${inlineMd(raw)}</p>`;
 i++;
 }

 return html;
}

function copyCodeBlock(btn) {
 const wrap = btn.closest('.code-block-wrap');
 if (!wrap) return;
 const code = wrap.querySelector('code')?.innerText || '';
 navigator.clipboard.writeText(code).then(() => {
 const orig = btn.innerHTML;
 btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
 btn.classList.add('copied');
 setTimeout(() => {
 btn.innerHTML = orig;
 btn.classList.remove('copied');
 }, 2000);
 }).catch(() => {
 const ta = document.createElement('textarea');
 ta.value = code;
 document.body.appendChild(ta);
 ta.select();
 document.execCommand('copy');
 document.body.removeChild(ta);
 btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
 btn.classList.add('copied');
 setTimeout(() => {
 btn.innerHTML = '<i class="bi bi-clipboard"></i> Copy';
 btn.classList.remove('copied');
 }, 2000);
 });
}

function copyResponseText(btn) {
 const bubble = btn.closest('.chat-msg')?.querySelector('.msg-bubble');
 if (!bubble) return;
 const text = bubble.innerText;
 navigator.clipboard.writeText(text).then(() => {
 const orig = btn.innerHTML;
 btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
 setTimeout(() => { btn.innerHTML = orig; }, 1800);
 });
}

function toggleSourcesCard(toggleEl) {
 const card = toggleEl.closest('.sources-card');
 if (card) {
 card.classList.toggle('open');
 }
}

function renderSourcesHtml(sources) {
 if (!sources || !Array.isArray(sources) || sources.length === 0) return '';

 const localSources = sources.filter(s => s.type !== 'web' && s.page !== 'Web');
 const webSources = sources.filter(s => s.type === 'web' || s.page === 'Web');

 let headerBadge = '';
 if (localSources.length > 0 && webSources.length > 0) {
 headerBadge = `<span class="sources-badge-dual"><i class="bi bi-layers-half text-primary"></i> Grounded in ${localSources.length} Course Notes &amp; ${webSources.length} Live Web Sources</span>`;
 } else if (localSources.length > 0) {
 headerBadge = `<span class="sources-badge-local"><i class="bi bi-file-earmark-pdf-fill text-danger"></i> Grounded in ${localSources.length} Course Notes</span>`;
 } else {
 headerBadge = `<span class="sources-badge-web"><i class="bi bi-globe2 text-info"></i> Grounded in ${webSources.length} Live Web Sources</span>`;
 }

 const items = sources.map(s => {
 const isWeb = s.type === 'web' || s.page === 'Web';
 if (isWeb) {
 const displayUrl = s.url ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="source-web-link"><i class="bi bi-box-arrow-up-right"></i> Open Link</a>` : '';
 return `
 <div class="source-item source-item-web">
 <div class="source-header">
 <span class="source-title"><i class="bi bi-globe2 text-info"></i> ${escapeHtml(s.doc_name)}</span>
 <span class="source-tag tag-web"><i class="bi bi-wifi"></i> Live Web</span>
 ${displayUrl}
 </div>
 <div class="source-snippet">${escapeHtml(s.snippet || '')}</div>
 </div>
 `;
 } else {
 return `
 <div class="source-item source-item-local">
 <div class="source-header">
 <span class="source-title"><i class="bi bi-file-earmark-pdf-fill text-danger"></i> ${escapeHtml(s.doc_name)}</span>
 <span class="source-tag tag-local"><i class="bi bi-file-earmark-text"></i> Page ${escapeHtml(String(s.page || 1))}</span>
 </div>
 <div class="source-snippet">${escapeHtml(s.snippet || '')}</div>
 </div>
 `;
 }
 }).join('');

 return `
 <div class="sources-card">
 <div class="sources-toggle" onclick="toggleSourcesCard(this)">
 ${headerBadge}
 <i class="bi bi-chevron-down chevron"></i>
 </div>
 <div class="sources-content">
 ${items}
 </div>
 </div>
 `;
}

function autoResizeChatInput(el) {
 if (!el) return;
 el.style.height = 'auto';
 el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

function applyQuickPrompt(promptText) {
  const inp = document.getElementById('chatInput');
  if (inp) {
    inp.value = promptText;
    autoResizeChatInput(inp);
    inp.focus();
  }
}

function renderDynamicChatWelcome() {
  const container = document.getElementById('dynamicChatChips');
  if (!container) return;

  fetch('/documents')
    .then(r => r.json())
    .then(data => {
      const docs = data.documents || [];
      const notes = S.notes || [];
      let chipsHtml = '';

      if (docs.length > 0) {
        // Show dynamic prompt chips from actual uploaded PDF documents
        docs.slice(0, 2).forEach(d => {
          const clean = d.replace(/\.pdf$/i, '').replace(/_/g, ' ');
          const short = clean.length > 24 ? clean.substring(0, 24) + '...' : clean;
          chipsHtml += `
            <button class="prompt-chip" onclick="applyQuickPrompt('Summarize key concepts from ${escapeHtml(clean)}')">
              <i class="bi bi-file-earmark-text"></i> Summarize: ${escapeHtml(short)}
            </button>
            <button class="prompt-chip" onclick="applyQuickPrompt('Give me practice test questions on ${escapeHtml(clean)}')">
              <i class="bi bi-journal-check"></i> Practice: ${escapeHtml(short)}
            </button>
          `;
        });
        chipsHtml += `
          <button class="prompt-chip" onclick="applyQuickPrompt('What are today\\'s latest current affairs news headlines?')">
            <i class="bi bi-newspaper"></i> Today's Current Affairs
          </button>
          <button class="prompt-chip" onclick="applyQuickPrompt('Create an optimal 4-stage study plan for my exam revision')">
            <i class="bi bi-calendar3"></i> Create Study Plan
          </button>
        `;
      } else if (notes.length > 0) {
        // Show dynamic study note prompt chips
        notes.slice(0, 2).forEach(n => {
          const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
          const title = n.title || (lines[0] ? lines[0].substring(0, 24) : 'Personal Note');
          const short = title.length > 24 ? title.substring(0, 24) + '...' : title;
          chipsHtml += `
            <button class="prompt-chip" onclick="applyQuickPrompt('Explain key takeaways from my study note: ${escapeHtml(title)}')">
              <i class="bi bi-journal-text"></i> Review Note: ${escapeHtml(short)}
            </button>
          `;
        });
        chipsHtml += `
          <button class="prompt-chip" onclick="applyQuickPrompt('What are today\\'s latest current affairs news headlines?')">
            <i class="bi bi-newspaper"></i> Today's Current Affairs
          </button>
          <button class="prompt-chip" onclick="applyQuickPrompt('Create an optimal 4-stage study plan for my exam revision')">
            <i class="bi bi-calendar3"></i> Create Study Plan
          </button>
        `;
      } else {
        // Default clean 2D category chips
        chipsHtml = `
          <button class="prompt-chip" onclick="applyQuickPrompt('What are today\\'s latest current affairs news headlines?')">
            <i class="bi bi-newspaper"></i> Today's Current Affairs
          </button>
          <button class="prompt-chip" onclick="applyQuickPrompt('Create an optimal 4-stage study plan for my exam revision')">
            <i class="bi bi-calendar3"></i> Create Study Plan
          </button>
          <button class="prompt-chip" onclick="applyQuickPrompt('Generate a 5-question conceptual practice quiz with explanations')">
            <i class="bi bi-journal-check"></i> Practice Quiz
          </button>
          <button class="prompt-chip" onclick="applyQuickPrompt('Explain the core differences between dynamic programming and divide and conquer')">
            <i class="bi bi-diagram-3"></i> Core Concepts
          </button>
        `;
      }

      container.innerHTML = chipsHtml;
    })
    .catch(() => {
      container.innerHTML = `
        <button class="prompt-chip" onclick="applyQuickPrompt('What are today\\'s latest current affairs news headlines?')">
          <i class="bi bi-newspaper"></i> Today's Current Affairs
        </button>
        <button class="prompt-chip" onclick="applyQuickPrompt('Create an optimal 4-stage study plan for my exam revision')">
          <i class="bi bi-calendar3"></i> Create Study Plan
        </button>
      `;
    });
}

// ─────────────────────────────────────────
// Chat Threads Management
// ─────────────────────────────────────────
function initChatWorkspace() {
  populateChatDocFilter();
  renderDynamicChatWelcome();
  try {
    const savedModel = localStorage.getItem('studyedge_chat_model');
    const modelSel = document.getElementById('chatModelSelect');
    if (savedModel && modelSel) {
      modelSel.value = savedModel;
    }
  } catch (e) {}
  loadChatThreads();
  setupChatKeybindings();
}

function setupChatKeybindings() {
  const inp = document.getElementById('chatInput');
  if (inp && !inp.dataset.bound) {
    inp.dataset.bound = 'true';
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuestion();
      }
    });
  }
}

function populateChatDocFilter() {
  const sel = document.getElementById('chatDocFilter');
  if (!sel) return;

  fetch('/rag/status')
    .then(r => r.json())
    .then(data => {
      const docs = data.files || [];
      const currVal = sel.value;
      let opts = `
        <option value="auto">Auto: Smart Document Router</option>
        <option value="all">All Uploaded Documents (RAG)</option>
        <option value="none">General Academic Knowledge Only</option>
      `;
      docs.forEach(doc => {
        opts += `<option value="${escapeHtml(doc)}">${escapeHtml(doc)}</option>`;
      });
      sel.innerHTML = opts;
      if (currVal) {
        sel.value = currVal;
      } else {
        sel.value = "auto";
      }
    })
    .catch(() => {});
}

function loadChatThreads() {
 const sid = S.studentId || 1;
 const listEl = document.getElementById('chatThreadsList');
 if (!listEl) return;

 fetch(`/chat/threads?student_id=${sid}`)
 .then(r => r.json())
 .then(data => {
 chatThreadsList = data.threads || [];
 try {
 localStorage.setItem('studyedge_chat_threads', JSON.stringify(chatThreadsList));
 } catch (e) {}

 renderChatThreadsList();

 if (chatThreadsList.length > 0) {
 if (!currentChatThreadId || !chatThreadsList.some(t => t.id === currentChatThreadId)) {
 selectChatThread(chatThreadsList[0].id);
 } else {
 selectChatThread(currentChatThreadId);
 }
 } else {
 createNewChatThread();
 }
 })
 .catch(err => {
 try {
 const cached = localStorage.getItem('studyedge_chat_threads');
 if (cached) {
 chatThreadsList = JSON.parse(cached);
 renderChatThreadsList();
 if (chatThreadsList.length > 0) selectChatThread(chatThreadsList[0].id);
 }
 } catch (e) {}
 });
}

function renderChatThreadsList() {
 const listEl = document.getElementById('chatThreadsList');
 if (!listEl) return;

 if (chatThreadsList.length === 0) {
 listEl.innerHTML = `
 <div class="chat-threads-empty">
 <i class="bi bi-chat-square-dots" style="font-size:1.5rem;display:block;margin-bottom:6px"></i>
 No past chats yet. Start a new one!
 </div>
 `;
 return;
 }

 listEl.innerHTML = chatThreadsList.map(t => {
 const isActive = t.id === currentChatThreadId;
 return `
 <div class="chat-thread-item ${isActive ? 'active' : ''}" onclick="selectChatThread('${t.id}')">
 <div class="chat-thread-title-wrap">
 <i class="bi ${isActive ? 'bi-chat-left-dots-fill' : 'bi-chat-left-text'}"></i>
 <span class="chat-thread-title" title="${escapeHtml(t.title)}">${escapeHtml(t.title || 'New Chat')}</span>
 </div>
 <button class="chat-thread-del-btn" onclick="deleteChatThread('${t.id}', event)" title="Delete Chat">
 <i class="bi bi-trash3"></i>
 </button>
 </div>
 `;
 }).join('');
}

function createNewChatThread() {
  const sid = S.studentId || 1;
  const newId = 'chat_' + Date.now() + '_' + Math.random().toString(36).substring(2, 7);
  const docFilter = document.getElementById('chatDocFilter')?.value || 'all';

  fetch('/chat/threads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      student_id: sid,
      thread_id: newId,
      title: 'New Chat',
      doc_filter: docFilter
    })
  })
  .then(r => r.json())
  .then(data => {
    const threadObj = {
      id: newId,
      studentId: sid,
      title: 'New Chat',
      docFilter: docFilter,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    chatThreadsList.unshift(threadObj);
    renderChatThreadsList();
    selectChatThread(newId);
  })
  .catch(() => {
    currentChatThreadId = newId;
    renderChatThreadsList();
    resetChatBoxToWelcome();
  });
}

function selectChatThread(threadId) {
  currentChatThreadId = threadId;
  renderChatThreadsList();

  const activeThread = chatThreadsList.find(t => t.id === threadId);
  const titleEl = document.getElementById('chatActiveTitle');
  if (titleEl) {
    titleEl.textContent = activeThread ? (activeThread.title || 'New Chat') : 'Conversation';
  }

  const filterSel = document.getElementById('chatDocFilter');
  if (filterSel && activeThread && activeThread.docFilter) {
    filterSel.value = activeThread.docFilter;
  }

  const modelBadge = document.getElementById('chatModelName');
  if (modelBadge) {
    modelBadge.textContent = S.modelConfig.qa || 'mistral';
  }

  const chatBox = document.getElementById('chatBox');
  if (!chatBox) return;

  chatBox.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:center;height:180px;color:var(--muted);gap:10px">
      <div class="spinner-sm"></div> Loading conversation...
    </div>
  `;

  fetch(`/chat/threads/${threadId}`)
    .then(r => r.json())
    .then(data => {
      const msgs = data.messages || [];
      chatBox.innerHTML = '';
      currentChatMessages = [];
      if (msgs.length === 0) {
        resetChatBoxToWelcome();
      } else {
        msgs.forEach(m => {
          appendMessageCard(m.sender, m.content, m.sources, m.action || null, false);
        });
        chatBox.scrollTop = chatBox.scrollHeight;
      }
    })
    .catch(() => {
      resetChatBoxToWelcome();
    });
}

function resetChatBoxToWelcome() {
  currentChatMessages = [];
  const chatBox = document.getElementById('chatBox');
  if (!chatBox) return;
  chatBox.innerHTML = `
    <div class="chat-welcome" id="chatWelcomeScreen">
      <div class="welcome-gemini-icon"><i class="bi bi-chat-square-text-fill"></i></div>
      <h2>AI Academic Tutor &amp; Notes Companion</h2>
      <p>Ask anything — answers intelligently draw from your notes with full RAG citations and conversational memory.</p>
      <div class="quick-prompt-chips" id="dynamicChatChips"></div>
    </div>
  `;
  renderDynamicChatWelcome();
}

function deleteChatThread(threadId, event) {
 if (event) event.stopPropagation();
 if (!confirm('Are you sure you want to delete this chat?')) return;

 fetch(`/chat/threads/${threadId}?student_id=${S.studentId || 1}`, { method: 'DELETE' })
 .then(() => {
 chatThreadsList = chatThreadsList.filter(t => t.id !== threadId);
 renderChatThreadsList();
 if (currentChatThreadId === threadId) {
 if (chatThreadsList.length > 0) {
 selectChatThread(chatThreadsList[0].id);
 } else {
 createNewChatThread();
 }
 }
 })
 .catch(() => {
 chatThreadsList = chatThreadsList.filter(t => t.id !== threadId);
 renderChatThreadsList();
 });
}

function onChatDocFilterChange() {
 const sel = document.getElementById('chatDocFilter');
 if (!sel || !currentChatThreadId) return;
 const val = sel.value;
 const thread = chatThreadsList.find(t => t.id === currentChatThreadId);
 if (thread) thread.docFilter = val;
}


// ─────────────────────────────────────────
// Send Chat Message (with Conversational Memory)
// ─────────────────────────────────────────
function sendQuestion() {
 const inp = document.getElementById('chatInput');
 const q = inp?.value.trim();
 if (!q) return;

 inp.value = '';
 autoResizeChatInput(inp);

 const sb = document.getElementById('sendBtn');
 if (sb) sb.disabled = true;

 const welcome = document.getElementById('chatWelcomeScreen');
 if (welcome) welcome.remove();

 if (!currentChatThreadId) {
 currentChatThreadId = 'chat_' + Date.now();
 }

 // 1. Render User Message Card
 appendMessageCard('user', q, [], true);

 const modelSel = document.getElementById('chatModelSelect');
 const chosenModelSetting = modelSel ? modelSel.value : (S.modelConfig.qa || 'auto');
 const docFilter = document.getElementById('chatDocFilter')?.value || 'all';

 const modelBadge = document.getElementById('chatModelName');
 const activeLabel = chosenModelSetting === 'auto' ? 'Auto' : chosenModelSetting;

 // 2. Typing indicator
 const typingId = 'typing-' + Date.now();
 const chatBox = document.getElementById('chatBox');
 const typDiv = document.createElement('div');
 typDiv.id = typingId;
 typDiv.className = 'chat-msg bot';
 typDiv.innerHTML = `
 <div class="msg-name"><i class="bi bi-stars"></i> StudyEdge AI (${activeLabel})</div>
 <div class="msg-bubble">
 <div class="typing-dots">
 <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
 </div>
 </div>`;
 chatBox.appendChild(typDiv);
 chatBox.scrollTop = chatBox.scrollHeight;

 fetch('/chat/send', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 thread_id : currentChatThreadId,
 question : q,
 student_id : S.studentId || 1,
 student_name: S.studentName || 'Student',
 model : chosenModelSetting,
 doc_filter : docFilter
 })
 })
 .then(r => r.json())
 .then(data => {
 document.getElementById(typingId)?.remove();
 if (sb) sb.disabled = false;

 // 3. Render Bot Response with parsed markdown, code blocks & sources
 appendMessageCard('bot', data.answer || 'No response generated.', data.sources || [], data.action || null, true);

 // Update dynamically selected model if router chose one
 if (data.model) {
 if (modelBadge) modelBadge.textContent = data.model;
 S.activeModelName = data.model;
 updateActiveModelBar();
 }

 // If auto mode was used for doc scope, update UI indicator or thread state
 if (docFilter === 'auto' && data.doc_filter) {
 const filterSel = document.getElementById('chatDocFilter');
 if (filterSel && filterSel.value === 'auto') {
 const matchingOpt = Array.from(filterSel.options).find(o => o.value === data.doc_filter);
 if (matchingOpt) {
 const autoOpt = filterSel.querySelector('option[value="auto"]');
 if (autoOpt) autoOpt.textContent = ` Auto (${matchingOpt.text.replace(/^[^\w\s]+/, '').trim()})`;
 }
 }
 }

 // 4. Update Thread Title in Header and Sidebar
 if (data.thread_title) {
 const titleEl = document.getElementById('chatActiveTitle');
 if (titleEl) titleEl.textContent = data.thread_title;
 const th = chatThreadsList.find(t => t.id === currentChatThreadId);
 if (th) {
 th.title = data.thread_title;
 renderChatThreadsList();
 }
 }

 refreshStats();
 })
 .catch(err => {
 document.getElementById(typingId)?.remove();
 if (sb) sb.disabled = false;
 appendMessageCard('bot', ' Generation timed out or Ollama model error. Please ensure Ollama is running and try again.', [], true);
 });
}

function onChatModelChange() {
 const sel = document.getElementById('chatModelSelect');
 if (!sel) return;
 const val = sel.value;
 try {
 localStorage.setItem('studyedge_chat_model', val);
 } catch (e) {}
 if (val !== 'auto') {
 S.modelConfig.qa = val;
 S.activeModelName = val;
 updateActiveModelBar();
 }
}

function renderActionCardHtml(action) {
 if (!action) return '';
 const iconMap = {
 'planner': '<i class="bi bi-calendar-check-fill" style="color:#10b981;font-size:1.4rem"></i>',
 'test': '<i class="bi bi-patch-question-fill" style="color:#3b82f6;font-size:1.4rem"></i>',
 'pomodoro': '<i class="bi bi-stopwatch-fill" style="color:#ef4444;font-size:1.4rem"></i>',
 'report': '<i class="bi bi-bar-chart-line-fill" style="color:#8b5cf6;font-size:1.4rem"></i>'
 };
 const icon = iconMap[action.action_type] || '<i class="bi bi-lightning-charge-fill" style="color:#f59e0b;font-size:1.4rem"></i>';
 const payloadStr = encodeURIComponent(JSON.stringify(action.payload || {}));

 return `
 <div class="chat-action-card action-type-${escapeHtml(action.action_type)}">
 <div class="action-card-left">
 <div class="action-card-icon">${icon}</div>
 <div class="action-card-info">
 <div class="action-card-title">${escapeHtml(action.title || action.action_name)}</div>
 <div class="action-card-desc">${escapeHtml(action.description || '')}</div>
 </div>
 </div>
 <button class="action-card-btn" onclick="executeCrossModuleAction('${escapeHtml(action.action_type)}', '${payloadStr}')">
 ${escapeHtml(action.button_label || 'View Details')}
 </button>
 </div>
 `;
}

function executeCrossModuleAction(actionType, payloadEncoded) {
 let payload = {};
 try {
 payload = JSON.parse(decodeURIComponent(payloadEncoded));
 } catch (e) {}

 if (actionType === 'planner') {
 setView('planner');
 showToast(` Opened Study Planner! Scheduled "${payload.topic || 'Session'}".`);
 } else if (actionType === 'test') {
 setView('test');
 if (payload.doc_name) {
 const sel = document.getElementById('testDocSelect');
 if (sel) {
 for (let opt of sel.options) {
 if (opt.value.includes(payload.doc_name) || payload.doc_name.includes(opt.value)) {
 sel.value = opt.value;
 break;
 }
 }
 }
 }
 if (payload.num_questions) {
 const numSel = document.getElementById('testNumQuestions');
 if (numSel) numSel.value = payload.num_questions;
 }
 showToast(` Practice Exam Ready! Select chapters and click "Generate Full Test".`);
 } else if (actionType === 'pomodoro') {
 setView('home');
 const topicInp = document.getElementById('sessionTopic');
 if (topicInp && payload.topic) {
 topicInp.value = payload.topic;
 }
 showToast(`️ Switched to Focus Room for "${payload.topic || 'Session'}"!`);
 } else if (actionType === 'report') {
 if (payload.test_id) {
 inspectHistoricalReport(payload.test_id);
 } else {
 setView('reports');
 }
 }
}

let currentChatMessages = [];

function appendMessageCard(sender, content, sources, action = null, scroll = true) {
 const chatBox = document.getElementById('chatBox');
 if (!chatBox) return;

 const msgIndex = currentChatMessages.length;
 currentChatMessages.push({ sender, content, sources, action });

 const div = document.createElement('div');
 div.className = `chat-msg ${sender}`;
 div.setAttribute('data-msg-index', msgIndex);

 if (sender === 'user') {
 div.innerHTML = `
 <div class="msg-name">${escapeHtml(S.studentName || 'You')}</div>
 <div class="msg-bubble">${escapeHtml(content)}</div>
 `;
 } else {
 const formattedHtml = renderMarkdownToHtml(content);
 const actionHtml = renderActionCardHtml(action);
 const sourcesHtml = renderSourcesHtml(sources);
 div.innerHTML = `
 <div class="msg-name"><i class="bi bi-stars"></i> StudyEdge AI</div>
 <div class="msg-bubble">${formattedHtml}</div>
 ${actionHtml}
 ${sourcesHtml}
 <div class="msg-actions" style="margin-top:6px;display:flex;gap:6px">
 <button class="msg-act-btn" onclick="copyResponseText(this)">
 <i class="bi bi-clipboard"></i> Copy
 </button>
 <button class="msg-act-btn" onclick="speakText(this)" data-text="${escapeHtml(content)}">
 <i class="bi bi-volume-up"></i> Read
 </button>
 <button class="msg-act-btn" onclick="openSaveChatNotesModal('msg', ${msgIndex})">
 <i class="bi bi-journal-plus"></i> Save to Notes
 </button>
 </div>
 `;
 }

 chatBox.appendChild(div);
 if (scroll) {
 chatBox.scrollTop = chatBox.scrollHeight;
 }
}


// ─────────────────────────────────────────
// Studio Quick AI Tools
// ─────────────────────────────────────────
// ─────────────────────────────────────────
// Studio Quick AI Tools
// ─────────────────────────────────────────
function generateSummary() {
 const topic = document.getElementById('activeTopicName')?.textContent?.trim();
 if (topic && topic !== '—' && topic !== '-' && topic.toLowerCase() !== 'no active session') {
 // Summarize currently active study session topic
 const model = S.modelConfig.summary || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Summary';
 updateActiveModelBar();

 setView('home');
 setStudioLoading(true, `Summarizing active topic "${topic}" with ${model}...`);

 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic, student_name: S.studentName, model })
 })
 .then(r => r.json())
 .then(data => { setStudioLoading(false); setStudioOutput(data.summary || 'No summary generated.'); })
 .catch(() => { setStudioLoading(false); setStudioOutput('Error generating summary.'); });
 } else {
 // Open the Text Summary Studio source selector for Documents, Notes, or Custom Topics
 openSummaryModal();
 }
}

function openSummaryModal() {
 const spin = document.getElementById('summarySpin');
 if (spin) spin.style.display = 'none';

 // 1. Populate uploaded documents
 fetch('/documents')
 .then(r => r.json())
 .then(data => {
 const docs = data.documents || [];
 const dCount = document.getElementById('summaryDocsCount');
 if (dCount) dCount.textContent = docs.length;

 const docList = document.getElementById('summaryDocList');
 if (docList) {
 docList.innerHTML = docs.length
 ? docs.map(d => {
 const cleanTitle = d.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 return `
 <div class="summary-item-card" onclick="generateDocSummary('${escapeHtml(d)}')">
 <div class="audio-item-left">
 <div class="audio-item-icon" style="background:#fdf2f8;color:#db2777">
 <i class="bi bi-file-earmark-pdf-fill"></i>
 </div>
 <div class="audio-item-info">
 <span class="audio-item-title" title="${escapeHtml(d)}">${escapeHtml(cleanTitle)}</span>
 <div class="audio-item-sub">PDF Document • Click to generate study summary</div>
 </div>
 </div>
 <button class="btn-audio-listen">
 <i class="bi bi-card-list"></i> Summarize
 </button>
 </div>`;
 }).join('')
 : '<p class="empty-msg" style="text-align:center;padding:16px">No PDF documents uploaded yet. Upload a document from the left panel.</p>';
 }
 })
 .catch(() => {});

 // 2. Populate study notes
 const notes = S.notes || [];
 const nCount = document.getElementById('summaryNotesCount');
 if (nCount) nCount.textContent = notes.length;

 const noteList = document.getElementById('summaryNotesList');
 if (noteList) {
 noteList.innerHTML = notes.length
 ? notes.map(n => {
 const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
 const title = n.title || (lines[0] ? lines[0].substring(0, 50) : 'Personal Study Note');
 const snippet = (n.content || '').substring(0, 75).replace(/\n/g, ' ');
 return `
 <div class="summary-item-card" onclick="generateNoteSummary('${escapeHtml(String(n.id))}')">
 <div class="audio-item-left">
 <div class="audio-item-icon" style="background:#eef2ff;color:#4f46e5">
 <i class="bi bi-journal-text"></i>
 </div>
 <div class="audio-item-info">
 <span class="audio-item-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
 <div class="audio-item-sub">${escapeHtml(snippet)}${snippet.length >= 75 ? '...' : ''}</div>
 </div>
 </div>
 <button class="btn-audio-listen">
 <i class="bi bi-card-list"></i> Summarize
 </button>
 </div>`;
 }).join('')
 : '<p class="empty-msg" style="text-align:center;padding:16px">No study notes saved yet. Create a note from the Quick Tools panel.</p>';
 }

 // Default to documents tab
 switchSummaryTab('docs');

 const modal = document.getElementById('summaryModal');
 if (modal) modal.style.display = 'flex';
}

function switchSummaryTab(tab) {
 const docList = document.getElementById('summaryDocList');
 const noteList = document.getElementById('summaryNotesList');
 const customBox = document.getElementById('summaryCustomBox');
 const tabDocs = document.getElementById('summaryTabDocs');
 const tabNotes = document.getElementById('summaryTabNotes');
 const tabCustom = document.getElementById('summaryTabCustom');

 if (tab === 'docs') {
 if (docList) docList.style.setProperty('display', 'flex', 'important');
 if (noteList) noteList.style.setProperty('display', 'none', 'important');
 if (customBox) customBox.style.setProperty('display', 'none', 'important');
 if (tabDocs) tabDocs.classList.add('active');
 if (tabNotes) tabNotes.classList.remove('active');
 if (tabCustom) tabCustom.classList.remove('active');
 } else if (tab === 'notes') {
 if (docList) docList.style.setProperty('display', 'none', 'important');
 if (noteList) noteList.style.setProperty('display', 'flex', 'important');
 if (customBox) customBox.style.setProperty('display', 'none', 'important');
 if (tabDocs) tabDocs.classList.remove('active');
 if (tabNotes) tabNotes.classList.add('active');
 if (tabCustom) tabCustom.classList.remove('active');
 } else {
 if (docList) docList.style.setProperty('display', 'none', 'important');
 if (noteList) noteList.style.setProperty('display', 'none', 'important');
 if (customBox) customBox.style.setProperty('display', 'flex', 'important');
 if (tabDocs) tabDocs.classList.remove('active');
 if (tabNotes) tabNotes.classList.remove('active');
 if (tabCustom) tabCustom.classList.add('active');
 setTimeout(() => document.getElementById('summaryCustomInput')?.focus(), 50);
 }
}

function generateDocSummary(docName) {
 closeSummaryModal();
 setView('home');
 const model = S.modelConfig.summary || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Summary';
 updateActiveModelBar();

 const cleanTitle = docName.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 setStudioLoading(true, `Generating comprehensive AI summary for "${cleanTitle}"...`);

 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic: docName, student_name: S.studentName, model })
 })
 .then(r => r.json())
 .then(data => {
 setStudioLoading(false);
 setStudioOutput(data.summary || 'No summary generated.');
 showToast(` Generated summary for "${cleanTitle}"!`);
 })
 .catch(() => {
 setStudioLoading(false);
 setStudioOutput('Error generating summary for document.');
 showToast(' Failed to generate summary.');
 });
}

function generateNoteSummary(noteId) {
 const note = (S.notes || []).find(n => String(n.id) === String(noteId));
 if (!note) {
 showToast(' Note not found.');
 return;
 }
 closeSummaryModal();
 setView('home');
 const model = S.modelConfig.summary || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Summary';
 updateActiveModelBar();

 setStudioLoading(true, `Generating AI study summary for "${note.title || 'Study Note'}"...`);

 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 topic: note.title || 'Personal Study Note',
 student_name: S.studentName,
 model,
 note_content: note.content || ''
 })
 })
 .then(r => r.json())
 .then(data => {
 setStudioLoading(false);
 setStudioOutput(data.summary || note.content || 'No summary generated.');
 showToast(` Generated summary for "${note.title || 'Note'}"!`);
 })
 .catch(() => {
 setStudioLoading(false);
 setStudioOutput('Error generating summary for note.');
 showToast(' Failed to generate summary.');
 });
}

function generateCustomSummary() {
 const input = document.getElementById('summaryCustomInput');
 const topic = input?.value?.trim();
 if (!topic) {
 showToast(' Please enter a topic to summarize.');
 input?.focus();
 return;
 }
 closeSummaryModal();
 setView('home');
 const model = S.modelConfig.summary || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Summary';
 updateActiveModelBar();

 setStudioLoading(true, `Generating structured AI summary for "${topic}"...`);

 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic, student_name: S.studentName, model })
 })
 .then(r => r.json())
 .then(data => {
 setStudioLoading(false);
 setStudioOutput(data.summary || 'No summary generated.');
 showToast(` Generated summary for "${topic}"!`);
 })
 .catch(() => {
 setStudioLoading(false);
 setStudioOutput('Error generating summary.');
 });
}

function summarizeCurrentNote() {
 const ta = document.getElementById('noteTextarea');
 const content = ta ? ta.value.trim() : '';
 if (!content) {
 showToast(' Note is empty. Type some content first.');
 return;
 }
 const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
 const title = lines[0] ? lines[0].substring(0, 50) : 'Personal Study Note';

 closeNotes();
 setView('home');
 const model = S.modelConfig.summary || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Summary';
 updateActiveModelBar();

 setStudioLoading(true, `Generating AI study summary for "${title}"...`);

 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 topic: title,
 student_name: S.studentName,
 model,
 note_content: content
 })
 })
 .then(r => r.json())
 .then(data => {
 setStudioLoading(false);
 setStudioOutput(data.summary || content || 'No summary generated.');
 showToast(` Generated AI summary for "${title}"!`);
 })
 .catch(() => {
 setStudioLoading(false);
 setStudioOutput('Error generating summary for note.');
 });
}

function closeSummaryModal() {
 const m = document.getElementById('summaryModal');
 if (m) m.style.display = 'none';
}

function generateStudyQs() {
 const topic = document.getElementById('activeTopicName')?.textContent?.trim();
 if (!topic || topic === '—') {
 showToast(' Start a session with a topic first.');
 return;
 }
 const model = S.modelConfig.questions || 'mistral';
 S.activeModelName = model;
 S.activeModelTask = 'Test Gen';
 updateActiveModelBar();

 setView('home');
 setStudioLoading(true, `Generating flashcard questions with ${model}...`);

 fetch('/questions', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic, student_name: S.studentName, count: 5, model })
 })
 .then(r => r.json())
 .then(data => { setStudioLoading(false); setStudioOutput(data.questions || 'No questions generated.'); })
 .catch(() => { setStudioLoading(false); setStudioOutput('Error generating questions.'); });
}

function setStudioLoading(on, text) {
 const spin = document.getElementById('studioLoading');
 const out = document.getElementById('studioOutput');
 if (spin) {
 spin.style.display = on ? 'flex' : 'none';
 const lt = document.getElementById('studioLoadingText');
 if (lt && text) lt.textContent = text;
 }
 if (out) out.style.display = on ? 'none' : 'block';
}

function setStudioOutput(text) {
 const el = document.getElementById('studioOutput');
 if (el) el.innerHTML = `<p style="white-space:pre-wrap;line-height:1.6">${text}</p>`;
}

// ─────────────────────────────────────────
// ─────────────────────────────────────────
// Autonomous AI Tutor & Tester Study Studio
// ─────────────────────────────────────────
let _pendingNewTopic = null;
S.currentCurriculum = null;
S.currentRoundIdx = 0;
S.currentSubTab = 'study';

function formatSimpleMarkdown(text) {
 if (!text) return '';
 let h = text
 .replace(/^#+\s*$/gm, '') // Clean up stray isolated # lines
 .replace(/### (.*?)\n/g, '<h3 style="font-size:1rem;color:#0f172a;margin:12px 0 6px;font-weight:800">$1</h3>')
 .replace(/#### (.*?)\n/g, '<h4 style="font-size:0.88rem;color:#1e293b;margin:10px 0 4px;font-weight:700">$1</h4>')
 .replace(/## (.*?)\n/g, '<h2 style="font-size:1.1rem;color:#0f172a;margin:14px 0 8px;font-weight:800">$1</h2>')
 .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
 .replace(/\*(.*?)\*/g, '<em>$1</em>')
 .replace(/`([^`]+)`/g, '<code style="background:#f1f5f9;padding:2px 5px;border-radius:4px;color:#e11d48;font-size:0.85em">$1</code>')
 .replace(/^- (.*)/gm, '<li style="margin-left:16px;margin-bottom:4px;line-height:1.6">$1</li>')
 .replace(/^> (.*)/gm, '<blockquote style="border-left:3px solid #3b82f6;padding-left:10px;margin:8px 0;color:#334155;font-style:italic">$1</blockquote>')
 .replace(/\n\n/g, '<div style="height:8px"></div>');
 return h;
}

function getLiveTimerStr(fallback = '20:00') {
 const tDisp = document.getElementById('timerDisplay');
 if (tDisp && tDisp.textContent && tDisp.textContent.includes(':')) {
 return tDisp.textContent.trim();
 }
 return S.lastTimeStr || fallback;
}

function renderCurriculumBannerButtons(roundIdx, currentRound) {
 if (S.isBreakRunning) {
 return `
 <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
 <span class="badge" style="background:#fef3c7;color:#b45309;font-weight:800;padding:6px 12px;border-radius:20px;font-size:0.85rem">
 Break: <span id="studioBannerClock">${S.lastTimeStr || '05:00'}</span>
 </span>
 <button class="btn-primary" style="background:#f59e0b;color:white;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="cancelBreak()">
 <i class="bi bi-x-circle-fill"></i> End Break &amp; Study
 </button>
 <button class="btn-primary" style="background:#fee2e2;color:#b91c1c;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="endSession()">
 <i class="bi bi-stop-circle"></i> End Session
 </button>
 </div>
 `;
 }

 const isThisRoundRunning = S.isSprintRunning && (S.activeSprintRoundIdx === roundIdx);
 const isThisRoundPaused = S.isSprintPaused && (S.activeSprintRoundIdx === roundIdx);

 if (isThisRoundRunning) {
 return `
 <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
 <span class="badge" style="background:#dcfce7;color:#15803d;font-weight:800;padding:6px 12px;border-radius:20px;font-size:0.85rem">
  Live: <span id="studioBannerClock">${getLiveTimerStr('20:00')}</span>
 </span>
 <button class="btn-primary" style="background:white;color:#dc2626;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="stopTimer()">
 <i class="bi bi-pause-fill"></i> Pause
 </button>
 <button class="btn-primary" style="background:white;color:#d97706;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="startBreak()">
 <i class="bi bi-cup-hot"></i> Break
 </button>
 <button class="btn-primary" style="background:#f1f5f9;color:#334155;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="endSprint()" title="End this sprint countdown (keeps session open)">
 <i class="bi bi-stop-fill"></i> End Sprint
 </button>
 <button class="btn-primary" style="background:#fee2e2;color:#b91c1c;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="endSession()">
 <i class="bi bi-stop-circle"></i> End Session
 </button>
 </div>
 `;
 }

 if (isThisRoundPaused) {
 return `
 <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
 <span class="badge" style="background:#fef3c7;color:#b45309;font-weight:800;padding:6px 12px;border-radius:20px;font-size:0.85rem">
 Paused: <span id="studioBannerClock">${getLiveTimerStr('20:00')}</span>
 </span>
 <button class="btn-primary" style="background:white;color:#059669;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="startTimer()">
 <i class="bi bi-play-fill"></i> Resume
 </button>
 <button class="btn-primary" style="background:#f1f5f9;color:#334155;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="endSprint()" title="End this sprint countdown (keeps session open)">
 <i class="bi bi-stop-fill"></i> End Sprint
 </button>
 <button class="btn-primary" style="background:#fee2e2;color:#b91c1c;font-weight:800;font-size:0.8rem;padding:6px 12px;border:none;box-shadow:0 2px 6px rgba(0,0,0,0.1);cursor:pointer" onclick="endSession()">
 <i class="bi bi-stop-circle"></i> End Session
 </button>
 </div>
 `;
 }

 return `
 <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
 <button class="btn-primary" style="background:white;color:#059669;font-weight:800;font-size:0.82rem;padding:8px 16px;box-shadow:0 2px 8px rgba(0,0,0,0.1);border:none;cursor:pointer" onclick="startSprintFromCurriculum(${roundIdx})">
 <i class="bi bi-play-circle-fill"></i> Start Sprint (${currentRound.suggested_duration_mins || 20}m)
 </button>
 <button class="btn-primary" style="background:#f8fafc;color:#334155;font-weight:700;font-size:0.8rem;padding:8px 12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);border:1px solid #cbd5e1;cursor:pointer" onclick="pauseAndSaveSession()" title="Save session progress for later">
 <i class="bi bi-floppy-fill"></i> Save Session
 </button>
 </div>
 `;
}

function updateCurriculumBannerLive(data) {
 const wasBreak = S.isBreakRunning;
 S.lastTimeStr = data.time_str;
 S.isSprintRunning = !data.is_break;
 S.isSprintPaused = false;
 S.isBreakRunning = !!data.is_break;

 const clock = document.getElementById('studioBannerClock');
 if (clock) clock.textContent = data.time_str;

 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl && (!clock || wasBreak !== S.isBreakRunning)) {
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }
}

function updateCurriculumBannerPaused(data) {
 S.lastTimeStr = data.time_str;
 S.isSprintRunning = false;
 S.isSprintPaused = true;
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) {
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }
}

function resetCurriculumBannerToIdle() {
 S.isSprintRunning = false;
 S.isSprintPaused = false;
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) {
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }
}

let _previewTopic = '';
let _previewDocName = null;
let _previewPlanId = null;

function setSessionInputMode(mode) {
 const btnTopic = document.getElementById('btnSessionModeTopic');
 const btnDoc = document.getElementById('btnSessionModeDoc');
 const docWrap = document.getElementById('sessionDocSelectWrap');
 const topicInp = document.getElementById('topicInput');

 if (mode === 'doc') {
 if (btnDoc) {
 btnDoc.style.background = '#eff6ff';
 btnDoc.style.color = '#2563eb';
 btnDoc.style.borderColor = '#bfdbfe';
 btnDoc.style.fontWeight = '700';
 }
 if (btnTopic) {
 btnTopic.style.background = '#f8fafc';
 btnTopic.style.color = '#64748b';
 btnTopic.style.borderColor = '#e2e8f0';
 btnTopic.style.fontWeight = '600';
 }
 if (docWrap) docWrap.style.display = 'block';
 populateSessionDocSelect();
 if (topicInp) topicInp.placeholder = "Topic or focus from this document or note...";
 } else {
 if (btnTopic) {
 btnTopic.style.background = '#eff6ff';
 btnTopic.style.color = '#2563eb';
 btnTopic.style.borderColor = '#bfdbfe';
 btnTopic.style.fontWeight = '700';
 }
 if (btnDoc) {
 btnDoc.style.background = '#f8fafc';
 btnDoc.style.color = '#64748b';
 btnDoc.style.borderColor = '#e2e8f0';
 btnDoc.style.fontWeight = '600';
 }
 if (docWrap) docWrap.style.display = 'none';
 S.selectedSessionDoc = null;
 const docSel = document.getElementById('sessionDocSelect');
 if (docSel) docSel.value = '';
 if (topicInp) topicInp.placeholder = "Topic to study (e.g. English, World History, Math)...";
 }
}

function onSessionDocSelectChange(sel) {
 const val = sel?.value || '';
 S.selectedSessionDoc = val || null;
 if (val) {
 const selectedOpt = sel.selectedOptions ? sel.selectedOptions[0] : null;
 const isSaved = val.startsWith('saved_session:');
 const isMyNote = val.startsWith('my_note:') || val.startsWith('user_note:');
 const topicVal = selectedOpt ? (selectedOpt.getAttribute('data-topic') || selectedOpt.textContent.replace(/^[]\s*/, '').replace(/\s*\(.*$/, '')) : val.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 const topicInp = document.getElementById('topicInput');
 if (topicInp && topicVal) topicInp.value = topicVal;
 if (isSaved) {
 showToast(` Selected saved session: "${topicVal}". Click "Begin Session" to resume or re-learn!`);
 } else if (isMyNote) {
 showToast(` Selected personal note: "${topicVal}". Click "Begin Session" to formulate your study sprint!`);
 } else {
 showToast(` Selected PDF: "${topicVal}". Click "Begin Session" to preview!`);
 }
 }
}

function openSessionPreviewModal(topic, docName = null, planId = null) {
 const modal = document.getElementById('sessionPreviewModal');
 _previewTopic = topic;
 _previewDocName = docName || null;
 _previewPlanId = planId;

 if (!modal) {
 prepareAndGenerateCurriculum(topic, planId, _previewDocName);
 return;
 }

 const topicEl = document.getElementById('sessionPreviewTopic');
 if (topicEl) topicEl.textContent = topic;

 const srcEl = document.getElementById('sessionPreviewSource');
 if (srcEl) {
 if (_previewDocName && _previewDocName.startsWith('saved_session:')) {
 const sId = _previewDocName.split(':')[1];
 srcEl.textContent = ` Saved Study Notes (Session #${sId})`;
 } else if (_previewDocName && (_previewDocName.startsWith('my_note:') || _previewDocName.startsWith('user_note:'))) {
 srcEl.textContent = ` Personal Note: ${topic}`;
 } else if (_previewDocName) {
 srcEl.textContent = ` Document Note: ${_previewDocName}`;
 } else {
 srcEl.textContent = ' Academic Knowledge & Live Web Grounding';
 }
 }

 const sumEl = document.getElementById('sessionPreviewSummary');
 if (sumEl) {
 sumEl.innerHTML = '<span style="color:#64748b"><i class="bi bi-hourglass-split"></i> Formulating personalized study sprint preview...</span>';
 }

 const focusInput = document.getElementById('sessionCustomFocusInput');
 if (focusInput) focusInput.value = '';

 modal.style.display = 'flex';

 fetch('/session/preview-plan', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ topic, doc_name: _previewDocName, student_id: S.studentId || 1 })
 })
 .then(r => r.json())
 .then(data => {
 if (data.summary && sumEl) {
 sumEl.textContent = data.summary;
 }
 })
 .catch(() => {
 if (sumEl) {
 sumEl.textContent = `A 4-stage mastery curriculum on ${topic}, guiding you from fundamental definitions and mechanisms to active recall and exam-level verification.`;
 }
 });
}

function closeSessionPreviewModal() {
 const modal = document.getElementById('sessionPreviewModal');
 if (modal) modal.style.display = 'none';
}

function confirmStartPreviewedSession() {
 const focusInput = document.getElementById('sessionCustomFocusInput');
 const customFocus = focusInput ? focusInput.value.trim() : '';

 closeSessionPreviewModal();
 prepareAndGenerateCurriculum(_previewTopic, _previewPlanId, _previewDocName, customFocus);
}

function startSession() {
 const topicEl = document.getElementById('topicInput');
 const topic = topicEl?.value.trim();
 if (!topic) { showToast(' Enter a topic or choose an uploaded note to study.'); return; }

 const isDocMode = document.getElementById('sessionDocSelectWrap')?.style.display !== 'none';
 const targetDoc = isDocMode ? S.selectedSessionDoc : null;

 // Check if a session is already running
 if (S.sessionId) {
 const curTopic = document.getElementById('activeTopicName')?.textContent || 'Current Session';
 const curTime = document.getElementById('timerDisplay')?.textContent || '25:00';
 _pendingNewTopic = topic;
 const cct = document.getElementById('conflictCurrentTopic');
 if (cct) cct.textContent = curTopic;
 const ctime = document.getElementById('conflictCurrentTime');
 if (ctime) ctime.textContent = curTime;
 const cnt = document.getElementById('conflictNewTopic');
 if (cnt) cnt.textContent = topic;
 const scm = document.getElementById('sessionConflictModal');
 if (scm) scm.style.display = 'flex';
 return;
 }

 openSessionPreviewModal(topic, targetDoc);
}

function resolveSessionConflict(action) {
 const modal = document.getElementById('sessionConflictModal');
 if (modal) modal.style.display = 'none';

 const isDocMode = document.getElementById('sessionDocSelectWrap')?.style.display !== 'none';
 const targetDoc = isDocMode ? S.selectedSessionDoc : null;

 if (action === 'pause') {
 stopTimer();
 showToast(' Active session paused.');
 } else if (action === 'continue') {
 startTimer();
 showToast(' Continuing active session.');
 } else if (action === 'override') {
 const nextTopic = _pendingNewTopic || 'Focus Session';
 _pendingNewTopic = null;
 if (S.sessionId) {
 fetch('/session/end', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ session_id: parseInt(S.sessionId), student_id: parseInt(S.studentId) })
 }).finally(() => {
 S.sessionId = null;
 localStorage.removeItem('session_id');
 openSessionPreviewModal(nextTopic, targetDoc);
 });
 } else {
 openSessionPreviewModal(nextTopic, targetDoc);
 }
 } else if (action === 'cancel') {
 _pendingNewTopic = null;
 showToast('Cancelled.');
 }
}

let _curriculumAbortController = null;

function prepareAndGenerateCurriculum(topic, planId = null, docName = null, customFocus = null, autoStart = false) {
 const outEl = document.getElementById('studioOutput');
 const spinEl = document.getElementById('studioLoading');
 if (spinEl) spinEl.style.display = 'none';

 const cleanDoc = docName || S.selectedSessionDoc || null;

 // If user selected a saved note directly, resume/relearn it immediately
 if (cleanDoc && cleanDoc.startsWith('saved_session:')) {
 const savedId = cleanDoc.split(':')[1];
 resumeOrRelearnSession(savedId);
 return;
 }

 // Abort any prior in-flight generation
 if (_curriculumAbortController) {
 try { _curriculumAbortController.abort(); } catch (e) {}
 }
 _curriculumAbortController = new AbortController();
 const curSignal = _curriculumAbortController.signal;

 // 1. Show pre-sprint generation screen in AI OUTPUT
 if (outEl) {
 outEl.style.display = 'block';
 outEl.innerHTML = `
 <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:28px 20px;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.04)">
 <div style="display:inline-flex;align-items:center;gap:8px;background:#eff6ff;color:#2563eb;padding:6px 16px;border-radius:20px;font-weight:800;font-size:0.8rem;margin-bottom:12px">
 <i class="bi bi-cpu-fill"></i> Autonomous AI Study Architect
 </div>
 <h3 style="font-size:1.2rem;color:#0f172a;margin-bottom:6px;font-weight:800">Curating Mastery Curriculum for: "${escapeHtml(topic)}"</h3>
 <p style="font-size:0.82rem;color:#64748b;max-width:500px;margin:0 auto 20px;line-height:1.5">
 ${cleanDoc ? `Grounding curriculum in uploaded note: <strong>${escapeHtml(cleanDoc)}</strong>...` : 'Retrieving foundational definitions and authoritative academic knowledge...'}
 ${customFocus ? `<br><span style="color:#2563eb;font-weight:700">Special Focus: "${escapeHtml(customFocus)}"</span>` : ''}
 </p>
 <div style="display:flex;justify-content:center;gap:20px;flex-wrap:wrap;font-size:0.82rem;color:#334155;font-weight:700">
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Analyzing Concepts
 </div>
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Structuring Pomodoros
 </div>
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Formulating Drills
 </div>
 </div>
 </div>
 `;
 }

 // First generate session in backend
 fetch('/session/start', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ student_id: parseInt(S.studentId || 1), topic, plan_id: planId, doc_name: cleanDoc }),
 signal : curSignal
 })
 .then(r => r.json())
 .then(sData => {
 if (!sData.session_id || curSignal.aborted) return;
 S.sessionId = sData.session_id;
 const targetSessionId = sData.session_id;
 localStorage.setItem('session_id', S.sessionId);
 document.getElementById('sessionStartPanel').style.display = 'none';
 document.getElementById('activeSessionInfo').style.display = 'block';
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = topic;
 const tEnd = document.getElementById('timerEndBtn');
 if (tEnd) tEnd.style.display = 'inline-flex';
 const examBtn = document.getElementById('btnExamFromSession');
 if (examBtn) examBtn.style.display = 'inline-flex';

 if (autoStart) {
 S.isSprintRunning = true;
 S.isSprintPaused = false;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) sBtn.style.display = 'none';
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'inline-flex';
 socket.emit('start_timer', {
 session_id : S.sessionId,
 student_id : S.studentId,
 is_break : false,
 duration_mins: 25,
 topic : topic,
 restart : true
 });
 }

 loadTodayPlans();
 loadUpcomingPlans();
 refreshStats();

 // Call curriculum generation route with doc_name and custom_focus
 return fetch('/session/curriculum/generate', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic, student_id: parseInt(S.studentId), session_id: targetSessionId, doc_name: cleanDoc, custom_focus: customFocus, plan_id: planId }),
 signal : curSignal
 })
 .then(r => r.json())
 .then(cData => {
 if (!S.sessionId || String(S.sessionId) !== String(targetSessionId) || curSignal.aborted) {
 console.log('[Curriculum] Generation finished but session was ended or changed. Discarding output.');
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 return;
 }
 if (cData.success && cData.curriculum) {
 S.currentCurriculum = cData.curriculum;
 renderCurriculumStudio(cData.curriculum, 0);
 const curPreset = localStorage.getItem('studyedge_studio_preset') || 'normal';
 setStudioPreset(curPreset);
 fetchInteractiveMilestones(targetSessionId, topic, cleanDoc);
 startSprintFromCurriculum(0);
 showToast('🚀 Sprint 1 Active & Synchronized with AI Curriculum!');
 } else {
 if (!S.sessionId) {
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 } else {
 showToast(' Using default session format.');
 }
 }
 });
 })
 .catch(err => {
 if (err.name === 'AbortError') {
 console.log('[Curriculum] Generation request aborted cleanly.');
 } else {
 console.error('[Curriculum error]', err);
 }
 if (!S.sessionId) {
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }
 });
}

function renderCurriculumStudio(curriculum, roundIdx = 0) {
 S.currentCurriculum = curriculum;
 S.currentRoundIdx = roundIdx;
 const outEl = document.getElementById('studioOutput');
 if (!outEl) return;
 outEl.classList.remove('raw-text');
 outEl.scrollLeft = 0;

 const rounds = curriculum.rounds || [];
 const currentRound = rounds[roundIdx] || rounds[0] || {};
 const isTutor = (currentRound.mode || '').toLowerCase() === 'tutor';

 // Synchronize top-left Pomodoro stat and stage label immediately
 const roundNum = roundIdx + 1;
 const pmCount = document.getElementById('pomodoroCount');
 if (pmCount) pmCount.textContent = `R${roundNum}`;
 const pmLbl = document.getElementById('pomodoroStatLbl');
 if (pmLbl) pmLbl.textContent = `Stage ${roundNum}`;
 updateRoundDots(roundNum);

 // Update timer display to suggested stage duration if sprint is not running
 if (!S.isSprintRunning && currentRound.suggested_duration_mins) {
 const durMins = currentRound.suggested_duration_mins || 20;
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = `${String(durMins).padStart(2, '0')}:00`;
 }

 // Synchronize left sidebar Sprint Milestones directly from the canonical curriculum stages!
 if (rounds && rounds.length > 0) {
 const curriculumMilestones = rounds.map((r, idx) => {
 const rNum = r.round_number || (idx + 1);
 const rTitle = r.title || `Stage ${rNum}`;
 const rObj = r.objective || r.focus || `Master Stage ${rNum} concepts.`;
 const isDone = (_cachedDesktopMilestones && _cachedDesktopMilestones[idx]) ? !!_cachedDesktopMilestones[idx].done : false;
 return {
 title: `Stage ${rNum}: ${rTitle}`,
 goal: rObj,
 tip: 'Study the guide notes and complete the stage practice drill.',
 done: isDone
 };
 });
 renderDesktopMilestones(curriculumMilestones);

 // Save canonical curriculum milestones to server so mobile also receives them!
 if (S.sessionId) {
 fetch('/session/set-milestones', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ session_id: parseInt(S.sessionId), milestones: curriculumMilestones })
 }).catch(() => {});
 }
 } else if (typeof renderDesktopMilestones === 'function') {
 renderDesktopMilestones();
 }

 let roundNavHtml = '';
 rounds.forEach((r, idx) => {
 const isActive = idx === roundIdx;
 const rMode = r.mode === 'Tutor' ? ' Tutor' : ' Tester';
 roundNavHtml += `
 <div class="round-nav-btn ${isActive ? 'active' : ''}" onclick="switchCurriculumRound(${idx})">
 <div class="round-nav-num">
 <span>R${r.round_number}: ${r.suggested_duration_mins}m</span>
 <span style="font-size:0.65rem;opacity:0.9">${rMode}</span>
 </div>
 <div class="round-nav-sub" title="${r.title}">${r.title}</div>
 </div>
 `;
 });

 const sourceBadgeClass = (curriculum.source_type || '').includes('Web') ? 'hybrid' : 'time';

 // Make Exam Mode button in studio header visible
 const examBtn = document.getElementById('btnExamFromSession');
 if (examBtn) examBtn.style.display = 'inline-flex';

 let subTabContent = '';
 if (S.currentSubTab === 'study') {
 subTabContent = `
 <div class="curriculum-subtab-toolbar">
 <div class="curriculum-subtab-title"><i class="bi bi-book-half" style="color:#4f46e5"></i> Stage Study Notes</div>
 <div class="curriculum-subtab-actions">
 <button class="btn-subtab-action" onclick="expandCurriculum('replan_round')" title="Re-synthesize this stage from notes and web"><i class="bi bi-arrow-repeat"></i> Replan Stage</button>
 <button class="btn-subtab-action primary" onclick="expandCurriculum('deeper_notes')" title="Generate deeper in-depth notes, mechanisms & examples"><i class="bi bi-file-earmark-plus"></i> Deepen Notes (+Examples)</button>
 </div>
 </div>
 <div class="curriculum-notes-body">
 ${formatSimpleMarkdown(currentRound.study_content_markdown || 'No study notes available for this stage.')}
 </div>
 `;
 } else if (S.currentSubTab === 'drills') {
 const drills = currentRound.practice_drills || [];
 let drillsListHtml = '';
 if (drills.length === 0) {
 drillsListHtml = `<div style="padding:16px;text-align:center;color:#64748b;font-size:0.84rem">No active recall questions for this round yet. Click below to generate!</div>`;
 } else {
 drillsListHtml = drills.map((d, dIdx) => {
 const isAns = !!d.answered;
 const optionsHtml = (d.options || []).map((opt, oIdx) => {
 let btnStyle = '';
 let iconHtml = '';
 let disAttr = '';
 if (isAns) {
 disAttr = 'disabled';
 if (oIdx === d.correct_index) {
 btnStyle = 'background:#dcfce7;border-color:#22c55e;color:#15803d;font-weight:700;';
 iconHtml = ' <i class="bi bi-check-circle-fill" style="color:#16a34a"></i>';
 } else if (oIdx === d.user_opt && !d.is_correct) {
 btnStyle = 'background:#fee2e2;border-color:#ef4444;color:#b91c1c;font-weight:700;';
 iconHtml = ' <i class="bi bi-x-circle-fill" style="color:#dc2626"></i>';
 }
 }
 return `
 <button class="curriculum-drill-opt" id="cDrill_${roundIdx}_${dIdx}_${oIdx}" style="${btnStyle}" ${disAttr} onclick="answerCurriculumDrill(${roundIdx}, ${dIdx}, ${oIdx})">
 <span style="font-weight:700;color:#64748b;margin-right:6px">${String.fromCharCode(65 + oIdx)}.</span> ${opt}${iconHtml}
 </button>
 `;
 }).join('');

 let fbStyle = 'display:none;';
 let fbContent = '';
 if (isAns) {
 fbStyle = `display:block;margin-top:8px;padding:8px 12px;border-radius:6px;font-size:0.8rem;line-height:1.4;background:${d.is_correct ? '#f0fdf4' : '#fef2f2'};border:1px solid ${d.is_correct ? '#86efac' : '#fca5a5'};color:${d.is_correct ? '#166534' : '#991b1b'}`;
 fbContent = d.is_correct 
 ? `<strong> Correct! (+30 Knowledge Points)</strong><br/>${d.explanation || ''}`
 : `<strong>Incorrect.</strong> ${d.explanation || ''}`;
 } else {
 fbStyle = 'display:none;margin-top:8px;padding:8px 12px;border-radius:6px;font-size:0.8rem;line-height:1.4';
 }

 return `
 <div class="curriculum-drill-card">
 <div style="font-weight:700;font-size:0.88rem;color:#0f172a;margin-bottom:8px">
 <span style="color:#4f46e5;margin-right:4px">Q${dIdx + 1}:</span> ${d.question}
 </div>
 <div style="display:flex;flex-direction:column;gap:6px">
 ${optionsHtml}
 </div>
 <div id="cDrillFeedback_${roundIdx}_${dIdx}" style="${fbStyle}">${fbContent}</div>
 </div>
 `;
 }).join('');
 }

 subTabContent = `
 <div class="curriculum-subtab-toolbar">
 <div class="curriculum-subtab-title"><i class="bi bi-lightning-charge-fill" style="color:#f59e0b"></i> Active Recall Practice</div>
 <div class="curriculum-subtab-actions">
 <button class="btn-subtab-action" onclick="expandCurriculum('replan_round')" title="Regenerate drills"><i class="bi bi-arrow-repeat"></i> Regenerate Drills</button>
 <button class="btn-subtab-action primary" onclick="expandCurriculum('more_drills')" title="Add 3 more practice drills"><i class="bi bi-plus-circle"></i> Add 3 More Drills</button>
 </div>
 </div>
 ${drillsListHtml}
 `;
 } else if (S.currentSubTab === 'checkpoints') {
 const chks = currentRound.active_checkpoints || [];
 let chksListHtml = chks.map((c, cIdx) => `
 <div class="milestone-item ${c.done ? 'done' : ''}" onclick="toggleCurriculumCheckpoint(${roundIdx}, ${cIdx})" style="padding:8px 10px;margin-bottom:8px">
 <input type="checkbox" class="milestone-cb" ${c.done ? 'checked' : ''} onclick="event.stopPropagation();toggleCurriculumCheckpoint(${roundIdx}, ${cIdx})"/>
 <div class="milestone-content">
 <div class="milestone-title" style="font-size:0.82rem">${c.task}</div>
 </div>
 <span style="font-size:0.7rem;font-weight:700;color:${c.done ? '#15803d' : '#4f46e5'}">${c.done ? '+15 KP ' : '+15 KP'}</span>
 </div>
 `).join('');

 subTabContent = `
 <div class="curriculum-subtab-toolbar">
 <div class="curriculum-subtab-title"><i class="bi bi-check2-circle" style="color:#10b981"></i> Mastery Checkpoints</div>
 <div class="curriculum-subtab-actions">
 <button class="btn-subtab-action" onclick="expandCurriculum('replan_round')" title="Replan checkpoints"><i class="bi bi-arrow-repeat"></i> Replan</button>
 <button class="btn-subtab-action primary" onclick="expandCurriculum('more_checkpoints')" title="Add 2 more checkpoints"><i class="bi bi-plus-circle"></i> Add 2 Checkpoints</button>
 </div>
 </div>
 ${chksListHtml}
 `;
 }

 outEl.style.display = 'block';
 outEl.innerHTML = `
 <div class="curriculum-studio">
 <div class="curriculum-header">
 <div>
 <div class="curriculum-title">
 <i class="bi bi-mortarboard-fill" style="color:#4f46e5"></i>
 ${curriculum.topic} — AI Study Studio
 </div>
 <div style="font-size:0.78rem;color:#64748b;margin-top:3px">${curriculum.overview || ''}</div>
 </div>
 <div class="curriculum-meta-badges">
 <span class="meta-badge ${sourceBadgeClass}"><i class="bi bi-globe"></i> ${curriculum.source_type || 'Local Notes'}</span>
 <span class="meta-badge time"><i class="bi bi-clock-fill"></i> Total: ${curriculum.total_suggested_mins || 75}m</span>
 <span class="meta-badge" style="background:#e0e7ff;color:#4338ca"><i class="bi bi-layers-fill"></i> 4 Pomodoro Stages</span>
 </div>
 </div>

 <!-- Rounds Step Navigation -->
 <div class="curriculum-rounds-nav">
 ${roundNavHtml}
 </div>

 <!-- Action Launch Banner -->
 <div class="curriculum-action-banner" id="curriculumActionBanner">
 <div>
 <div style="font-weight:800;font-size:0.95rem">
 Round ${currentRound.round_number}: ${currentRound.title}
 </div>
 <div style="font-size:0.75rem;opacity:0.9;margin-top:2px">
 ${currentRound.objective || ''}
 </div>
 </div>
 <div id="curriculumBannerControls">
 ${renderCurriculumBannerButtons(roundIdx, currentRound)}
 </div>
 </div>

 <!-- Sub Tabs -->
 <div class="curriculum-subtabs">
 <div class="curriculum-subtab ${S.currentSubTab === 'study' ? 'active' : ''}" onclick="switchCurriculumSubTab('study')">
 <i class="bi bi-book-half"></i> Study Material (${isTutor ? 'Tutor Mode' : 'Review'})
 </div>
 <div class="curriculum-subtab ${S.currentSubTab === 'drills' ? 'active' : ''}" onclick="switchCurriculumSubTab('drills')">
 <i class="bi bi-lightning-charge-fill" style="color:#f59e0b"></i> Active Drills (${currentRound.practice_drills?.length || 0})
 </div>
 <div class="curriculum-subtab ${S.currentSubTab === 'checkpoints' ? 'active' : ''}" onclick="switchCurriculumSubTab('checkpoints')">
 <i class="bi bi-check2-circle" style="color:#10b981"></i> Checkpoints (${currentRound.active_checkpoints?.length || 0})
 </div>
 </div>

 <!-- Content Container -->
 ${subTabContent}

 <!-- In-Studio AI Doubt / Explanation Assistant -->
 <div class="studio-doubt-box">
 <div class="studio-doubt-header">
 <i class="bi bi-lightbulb-fill" style="color:#f59e0b"></i> Have a doubt about this topic or note? Ask AI Tutor
 </div>
 <div class="studio-doubt-input-row">
 <input type="text" id="studioDoubtInput" class="studio-doubt-input" placeholder="Ask anything about this note (e.g. Can you explain what this concept means in simple words?)" onkeydown="if(event.key==='Enter') submitStudioDoubt()"/>
 <button class="studio-doubt-btn" onclick="submitStudioDoubt()"><i class="bi bi-send-fill"></i> Explain</button>
 </div>
 <div id="studioDoubtLoading" style="display:none;margin-top:10px;font-size:0.8rem;color:#64748b">
 <span class="spinner" style="display:inline-block;width:12px;height:12px;border-width:2px;margin-right:6px"></span> Synthesizing pedagogical explanation...
 </div>
 <div id="studioDoubtOutput" style="display:none" class="studio-doubt-response"></div>
 </div>
 </div>
 `;
}

function switchCurriculumRound(idx) {
 if (!S.currentCurriculum) return;
 S.currentRoundIdx = idx;
 const roundNum = idx + 1;
 const rounds = S.currentCurriculum.rounds || [];
 const currentRound = rounds[idx] || {};
 const durMins = currentRound.suggested_duration_mins || 20;

 // Update top-left pomodoro counter & stage label immediately
 const pmCount = document.getElementById('pomodoroCount');
 if (pmCount) pmCount.textContent = `R${roundNum}`;
 const pmLbl = document.getElementById('pomodoroStatLbl');
 if (pmLbl) pmLbl.textContent = `Stage ${roundNum}`;
 updateRoundDots(roundNum);

 // If a sprint is running or paused for a DIFFERENT round, adjust top-left buttons
 if (S.activeSprintRoundIdx !== idx) {
 // Top-left timer display shows this selected stage's target duration
 if (!S.isSprintRunning || S.isSprintPaused) {
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = `${String(durMins).padStart(2, '0')}:00`;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = `<i class="bi bi-play-fill"></i> Start Sprint ${roundNum}`;
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 }
 } else {
 // Display active sprint stage controls
 const sBtn = document.getElementById('startBtn');
 const pBtn = document.getElementById('pauseBtn');
 if (S.isSprintRunning) {
 if (sBtn) sBtn.style.display = 'none';
 if (pBtn) pBtn.style.display = 'inline-flex';
 } else if (S.isSprintPaused) {
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Resume';
 }
 if (pBtn) pBtn.style.display = 'none';
 }
 }

 renderCurriculumStudio(S.currentCurriculum, idx);
}

function switchCurriculumSubTab(subTab) {
 S.currentSubTab = subTab;
 if (S.currentCurriculum) {
 renderCurriculumStudio(S.currentCurriculum, S.currentRoundIdx || 0);
 }
}

function startSprintFromCurriculum(roundIdx) {
 if (!S.currentCurriculum) return;
 if (!S.sessionId) {
 const topic = S.currentCurriculum.topic || 'Focus Session';
 fetch('/session/start', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ student_id: parseInt(S.studentId || 1), topic })
 })
 .then(r => r.json())
 .then(sData => {
 S.sessionId = sData.session_id;
 localStorage.setItem('session_id', S.sessionId);
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = topic;
 startSprintFromCurriculum(roundIdx);
 });
 return;
 }
 const rounds = S.currentCurriculum.rounds || [];
 const r = rounds[roundIdx] || rounds[0];
 const durationMins = r.suggested_duration_mins || 20;
 const topic = `${S.currentCurriculum.topic} (R${r.round_number}: ${r.title})`;

 showToast(` Starting Sprint ${r.round_number}: ${r.title} (${durationMins} mins)...`);

 S.isSprintRunning = true;
 S.isSprintPaused = false;
 S.activeSprintRoundIdx = roundIdx;
 S.currentRoundIdx = roundIdx;

 // Immediately synchronize top-left Focus Timer UI
 const roundNum = roundIdx + 1;
 const pmCount = document.getElementById('pomodoroCount');
 if (pmCount) pmCount.textContent = `R${roundNum}`;
 const pmLbl = document.getElementById('pomodoroStatLbl');
 if (pmLbl) pmLbl.textContent = `Stage ${roundNum}`;
 updateRoundDots(roundNum);

 const tDisp = document.getElementById('timerDisplay');
 if (tDisp) tDisp.textContent = `${String(durationMins).padStart(2, '0')}:00`;

 const sBtn = document.getElementById('startBtn');
 if (sBtn) sBtn.style.display = 'none';
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'inline-flex';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'inline-flex';

 socket.emit('start_timer', {
 session_id : S.sessionId,
 student_id : S.studentId,
 is_break : false,
 duration_mins: durationMins,
 topic : topic,
 restart : true
 });

 // Update banner immediately to active state
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) ctrl.innerHTML = renderCurriculumBannerButtons(roundIdx, r);

 // Android Native Closed-App Alarm Scheduling
 if (window.StudyEdgeBridge && typeof window.StudyEdgeBridge.scheduleSystemAlarm === 'function') {
 window.StudyEdgeBridge.scheduleSystemAlarm(
 ` StudyEdge Sprint Complete: ${r.title}`,
 `Sprint ${r.round_number} (${durationMins}m) complete! Open StudyEdge to record your progress and take a break.`,
 durationMins * 60,
 1001
 );
 }
 playChimeSound();
}

function expandCurriculum(type) {
 if (!S.sessionId || !S.currentCurriculum) {
 showToast(' No active curriculum loaded.');
 return;
 }
 const roundIdx = S.currentRoundIdx || 0;
 const labels = {
 'more_drills': 'Generating 3 more practice drills with AI...',
 'more_checkpoints': 'Adding 2 actionable checkpoints...',
 'deeper_notes': 'Synthesizing in-depth examples & mechanism notes...',
 'replan_round': 'Replanning this study stage from notes & web...'
 };
 showToast(labels[type] || 'Updating curriculum...');

 const spinEl = document.getElementById('studioLoading');
 if (spinEl) {
 spinEl.style.display = 'flex';
 const st = document.getElementById('studioLoadingText');
 if (st) st.textContent = labels[type] || 'AI is expanding content...';
 }

 fetch('/session/curriculum/expand', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 session_id: S.sessionId,
 topic: S.currentCurriculum.topic,
 round_idx: roundIdx,
 expand_type: type,
 student_id: parseInt(S.studentId || 1)
 })
 })
 .then(async r => {
 const data = await r.json().catch(() => ({}));
 if (!r.ok) {
 throw new Error(data.error || `Server error (${r.status})`);
 }
 return data;
 })
 .then(data => {
 if (spinEl) spinEl.style.display = 'none';
 if (data.success && data.curriculum) {
 S.currentCurriculum = data.curriculum;
 renderCurriculumStudio(data.curriculum, roundIdx);
 showToast(' Curriculum updated with fresh content!');
 } else {
 showToast(' Could not expand content: ' + (data.error || 'Unknown error'));
 }
 })
 .catch(err => {
 if (spinEl) spinEl.style.display = 'none';
 console.error('[Expand error]', err);
 showToast(' Content expansion: ' + (err.message || 'AI engine is busy. Please retry.'));
 });
}

function openSavedSessionsModal() {
 const modal = document.getElementById('savedSessionsModal');
 const list = document.getElementById('savedSessionsList');
 if (!modal || !list) return;
 modal.style.display = 'flex';
 list.innerHTML = '<div class="empty-msg"><i class="bi bi-hourglass-split"></i> Loading saved sessions...</div>';

 fetch('/session/saved-list')
 .then(r => r.json())
 .then(data => {
 const sessions = data.sessions || [];
 if (!sessions.length) {
 list.innerHTML = '<div class="empty-msg"><i class="bi bi-journal-x"></i> No saved sessions found yet. Start a study session to generate one!</div>';
 return;
 }

 list.innerHTML = sessions.map(s => {
 const safeTopic = (s.topic || 'Session').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
 return `
 <div class="saved-session-card" id="savedCard_${s.session_id}">
 <div class="saved-session-info">
 <div class="saved-session-title" title="${escapeHtml(s.topic)}">
 <i class="bi bi-journal-bookmark-fill" style="color:#4f46e5;margin-right:6px;flex-shrink:0"></i>
 <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(s.topic)}</span>
 </div>
 <div class="saved-session-meta">
 <span><i class="bi bi-calendar3"></i> ${s.created_at}</span>
 <span><i class="bi bi-layers-fill"></i> ${s.rounds_count} Rounds</span>
 <span><i class="bi bi-clock"></i> ~${s.total_suggested_mins}m</span>
 </div>
 </div>
 <div class="saved-session-actions" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
 <button class="btn-primary" style="font-size:0.75rem;padding:6px 12px;background:#059669;color:white;border:none;cursor:pointer;border-radius:6px;font-weight:700;display:inline-flex;align-items:center;gap:4px" onclick="resumeOrRelearnSession('${s.session_id}', 'continue')" title="Continue from where you left off">
 <i class="bi bi-play-fill"></i> Continue
 </button>
 <button class="btn-primary" style="font-size:0.75rem;padding:6px 10px;background:#3b82f6;color:white;border:none;cursor:pointer;border-radius:6px;font-weight:700;display:inline-flex;align-items:center;gap:4px" onclick="resumeOrRelearnSession('${s.session_id}', 'restart')" title="Restart session from Round 1">
 <i class="bi bi-arrow-counterclockwise"></i> Restart
 </button>
 <button class="btn-primary" style="font-size:0.75rem;padding:6px 10px;background:#4f46e5;border:none;cursor:pointer;border-radius:6px;font-weight:700;display:inline-flex;align-items:center;gap:4px" onclick="openSessionExamConfigModal('${s.session_id}', '${safeTopic}')" title="Generate comprehensive test from this session">
 <i class="bi bi-patch-question-fill"></i> Launch Exam
 </button>
 <button class="btn-outline" style="font-size:0.75rem;padding:6px 8px;color:#dc2626;border-color:#fca5a5;cursor:pointer;border-radius:6px" onclick="deleteSavedSession('${s.session_id}')" title="Delete saved session details (preserves all tests)">
 <i class="bi bi-trash"></i>
 </button>
 </div>
 </div>
 `;
 }).join('');
 })
 .catch(() => {
 list.innerHTML = '<div class="empty-msg" style="color:#dc2626">Error loading saved sessions.</div>';
 });
}

async function resumeOrRelearnSession(sessionId, mode = 'continue') {
 try {
 showToast(mode === 'continue' ? 'Continuing saved study session...' : 'Restarting study session from beginning...', 'info');
 const res = await fetch('/session/load', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 session_id: sessionId,
 student_id: S.studentId || 1,
 mode: mode
 })
 });
 const d = await res.json();
 if (d.success && d.curriculum) {
 S.sessionId = d.session_id;
 localStorage.setItem('session_id', S.sessionId);
 S.currentCurriculum = d.curriculum;
 const targetRoundIdx = (d.round_idx !== undefined) ? d.round_idx : 0;
 S.currentRoundIdx = targetRoundIdx;
 S.isSprintRunning = false;
 S.isSprintPaused = (mode === 'continue');
 S.isBreakRunning = false;
 S.lastTimeStr = d.time_str || '20:00';

 // Update sidebar session controls
 const panel = document.getElementById('sessionStartPanel');
 const activeInfo = document.getElementById('activeSessionInfo');
 const activeTopic = document.getElementById('activeTopicName');
 const timerEndBtn = document.getElementById('timerEndBtn');
 const startBtn = document.getElementById('startBtn');
 const pauseBtn = document.getElementById('pauseBtn');

 if (panel) panel.style.display = 'none';
 if (activeInfo) activeInfo.style.display = 'block';
 if (activeTopic) activeTopic.textContent = d.topic || 'Study Session';
 if (timerEndBtn) timerEndBtn.style.display = 'inline-flex';
 if (startBtn) {
 startBtn.style.display = 'inline-flex';
 startBtn.innerHTML = mode === 'continue' ? '<i class="bi bi-play-fill"></i> Resume' : '<i class="bi bi-play-fill"></i> Start';
 }
 if (pauseBtn) pauseBtn.style.display = 'none';

 // Update timer display
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = S.lastTimeStr;

 // Update Pomodoro counter & stage label
 const roundNum = targetRoundIdx + 1;
 const pmCount = document.getElementById('pomodoroCount');
 if (pmCount) pmCount.textContent = `R${roundNum}`;
 const pmLbl = document.getElementById('pomodoroStatLbl');
 if (pmLbl) pmLbl.textContent = `Stage ${roundNum}`;
 updateRoundDots(roundNum);

 // Render curriculum studio to the specific continued/restarted round
 renderCurriculumStudio(d.curriculum, targetRoundIdx);

 // Close modal
 closeSavedSessionsModal();

 // Switch to dashboard view
 if (typeof setView === 'function') {
 setView('home');
 }

 showToast(mode === 'continue' ? ` Continuing session "${d.topic}" at Stage ${roundNum} (${S.lastTimeStr} remaining)` : ` Restarted session "${d.topic}" from Round 1`, 'success');
 } else {
 showToast(d.error || 'Failed to load session.', 'error');
 }
 } catch (err) {
 console.error('Error loading session:', err);
 showToast('Failed to load session.', 'error');
 }
}

function endSprint() {
 if (!S.sessionId) {
 showToast('No active session.', 'error');
 return;
 }
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 const durMins = currentRound.suggested_duration_mins || 20;

 if (socket) {
 socket.emit('end_sprint', {
 session_id: S.sessionId,
 student_id: S.studentId || 1,
 round_idx: S.currentRoundIdx || 0,
 suggested_mins: durMins,
 topic: S.currentCurriculum?.topic || 'Focus Session'
 });
 }

 S.isSprintRunning = false;
 S.isSprintPaused = false;
 S.isBreakRunning = false;
 S.lastTimeStr = `${String(durMins).padStart(2, '0')}:00`;

 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = S.lastTimeStr;

 const startBtn = document.getElementById('startBtn');
 const pauseBtn = document.getElementById('pauseBtn');
 const endSprintBtn = document.getElementById('endSprintBtn');
 if (startBtn) {
 startBtn.style.display = 'inline-flex';
 startBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 if (pauseBtn) pauseBtn.style.display = 'none';
 if (endSprintBtn) endSprintBtn.style.display = 'none';

 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) {
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }

 showToast(' Sprint ended. Your study notes and studio stay active!', 'success');
}

async function pauseAndSaveSession() {
 if (!S.sessionId) {
 showToast('No active session to save.', 'info');
 return;
 }
 try {
 const res = await fetch('/session/pause-save', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 session_id: S.sessionId,
 student_id: S.studentId || 1,
 round_idx: S.currentRoundIdx || 0
 })
 });
 const d = await res.json();
 if (d.success) {
 showToast(' Session progress saved for later! You can resume anytime from Saved Sessions.', 'success');
 }
 } catch (err) {
 console.error('[PauseSave error]', err);
 showToast('Failed to save session state.', 'error');
 }
}

async function submitStudioDoubt() {
 const inp = document.getElementById('studioDoubtInput');
 const loadEl = document.getElementById('studioDoubtLoading');
 const outEl = document.getElementById('studioDoubtOutput');
 if (!inp || !inp.value.trim()) return;

 const query = inp.value.trim();
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 const roundNotes = currentRound.study_content_markdown || '';
 const topic = S.currentCurriculum?.topic || 'General Study';

 if (loadEl) loadEl.style.display = 'block';
 if (outEl) outEl.style.display = 'none';

 try {
 const res = await fetch('/session/curriculum/ask-doubt', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 topic: topic,
 question: query,
 round_notes: roundNotes,
 session_id: S.sessionId,
 student_id: S.studentId || 1
 })
 });
 const d = await res.json();
 if (loadEl) loadEl.style.display = 'none';
 if (d.success && outEl) {
 outEl.style.display = 'block';
 outEl.innerHTML = `
 <div style="font-weight:700;margin-bottom:8px;color:#1e1b4b;display:flex;align-items:center;gap:6px">
 <i class="bi bi-robot" style="color:#4f46e5;font-size:1rem"></i> AI Tutor Pedagogical Clarification:
 </div>
 <div style="font-size:0.86rem;line-height:1.6">${renderMarkdownSafe(d.explanation_markdown)}</div>
 `;
 } else {
 if (outEl) {
 outEl.style.display = 'block';
 outEl.innerHTML = `<span style="color:#dc2626">${d.error || 'Failed to generate explanation.'}</span>`;
 }
 }
 } catch (err) {
 if (loadEl) loadEl.style.display = 'none';
 if (outEl) {
 outEl.style.display = 'block';
 outEl.innerHTML = `<span style="color:#dc2626">Network error communicating with AI Tutor.</span>`;
 }
 }
}

function closeSavedSessionsModal() {
 const modal = document.getElementById('savedSessionsModal');
 if (modal) modal.style.display = 'none';
}

function openSessionExamConfigModal(sessionId, topicName = '') {
 const modal = document.getElementById('sessionExamConfigModal');
 if (!modal) return;

 const targetId = sessionId || S.sessionId || localStorage.getItem('session_id');
 if (!targetId) {
 showToast(' No active session found. Please select a saved study session.');
 openSavedSessionsModal();
 return;
 }

 const topicEl = document.getElementById('sessionExamTargetTopic');
 const cleanTopic = topicName || S.currentCurriculum?.topic || document.getElementById('activeTopicName')?.textContent || 'Current Study';
 if (topicEl) topicEl.textContent = cleanTopic;

 const idInput = document.getElementById('selectedSessionExamId');
 if (idInput) idInput.value = targetId;

 // Default to 16 questions or previously selected
 selectSessionExamLength(16);
 setSessionExamTimerMode('timed');

 modal.style.display = 'flex';
}

function closeSessionExamConfigModal() {
 const modal = document.getElementById('sessionExamConfigModal');
 if (modal) modal.style.display = 'none';
}

function selectSessionExamLength(num, el) {
 const input = document.getElementById('selectedSessionExamLength');
 if (input) input.value = num;

 ['sessLen16', 'sessLen32', 'sessLen48', 'sessLen60'].forEach(id => {
 const card = document.getElementById(id);
 if (card) card.classList.remove('active');
 });

 const activeCard = el || document.getElementById(`sessLen${num}`);
 if (activeCard) activeCard.classList.add('active');

 const suggestedTimes = { 16: 15, 32: 30, 48: 45, 60: 60 };
 const sugSpan = document.getElementById('sessExamSuggestedTime');
 if (sugSpan) sugSpan.textContent = suggestedTimes[num] || 20;
}

function setSessionExamTimerMode(mode) {
 const timedLbl = document.getElementById('sessTimerTimedLabel');
 const untimedLbl = document.getElementById('sessTimerUntimedLabel');
 if (mode === 'timed') {
 if (timedLbl) timedLbl.classList.add('active');
 if (untimedLbl) untimedLbl.classList.remove('active');
 } else {
 if (timedLbl) timedLbl.classList.remove('active');
 if (untimedLbl) untimedLbl.classList.add('active');
 }
}

function confirmLaunchSessionExam() {
 const idInput = document.getElementById('selectedSessionExamId');
 const lenInput = document.getElementById('selectedSessionExamLength');
 const topicEl = document.getElementById('sessionExamTargetTopic');
 const timedLbl = document.getElementById('sessTimerTimedLabel');

 const sessionId = idInput ? idInput.value : (S.sessionId || localStorage.getItem('session_id'));
 const numQuestions = lenInput ? parseInt(lenInput.value, 10) : 16;
 const topicName = topicEl ? topicEl.textContent : 'Study Session';
 const timerMode = (timedLbl && timedLbl.classList.contains('active')) ? 'timed' : 'untimed';
 const suggestedTimes = { 16: 15, 32: 30, 48: 45, 60: 60 };
 const timeLimitMinutes = suggestedTimes[numQuestions] || 20;

 closeSessionExamConfigModal();
 executeExamGenerationFromSession(sessionId, topicName, numQuestions, timerMode, timeLimitMinutes);
}

function generateExamFromCurrentSession() {
 const curSessId = S.sessionId || localStorage.getItem('session_id');
 if (!curSessId) {
 showToast(' Choose a saved study session to generate an exam.');
 openSavedSessionsModal();
 return;
 }
 const curTopic = S.currentCurriculum?.topic || document.getElementById('activeTopicName')?.textContent || 'Current Study';
 openSessionExamConfigModal(curSessId, curTopic);
}

function generateExamFromSession(sessionId, topicName = '') {
 openSessionExamConfigModal(sessionId, topicName);
}

function executeExamGenerationFromSession(sessionId, topicName, numQuestions = 16, timerMode = 'timed', timeLimitMinutes = 20) {
 closeSavedSessionsModal();
 closeSessionExamConfigModal();
 setView('test');

 const cleanTopic = topicName || 'Study Session';
 showToast(` Formulating ${numQuestions}-question exam for "${cleanTopic}"...`);

 // Switch test view to loading state
 document.getElementById('testSetup').style.display = 'none';
 document.getElementById('testTakingContainer').style.display = 'none';
 document.getElementById('testResults').style.display = 'none';
 const loadEl = document.getElementById('testLoading');
 if (loadEl) loadEl.style.display = 'block';

 _updateTestLoadingProgress(
 `Synthesizing ${numQuestions} questions from session notes on "${cleanTopic}"...`,
 15,
 'Analyzing notes and applied drills across all stages...'
 );

 const model = S.modelConfig?.questions || 'mistral';
 const modelEl = document.getElementById('testLoadingModel');
 if (modelEl) modelEl.textContent = `Strict balance: Cognitive Memory, Logic, Critical Thinking & Creative Application`;

 // Start live elapsed timer
 if (_testLoadingTimerInterval) clearInterval(_testLoadingTimerInterval);
 _testLoadingElapsedSecs = 0;
 const timerEl = document.getElementById('testLoadingTimer');
 if (timerEl) timerEl.innerHTML = '<i class="bi bi-stopwatch"></i> Elapsed: 0s';
 _testLoadingTimerInterval = setInterval(() => {
 _testLoadingElapsedSecs++;
 const tEl = document.getElementById('testLoadingTimer');
 if (tEl) tEl.innerHTML = `<i class="bi bi-stopwatch"></i> Elapsed: ${_testLoadingElapsedSecs}s`;
 }, 1000);

 // Store user's configured timer settings for this test
 S.selectedTestLength = numQuestions;
 S.timerMode = timerMode;
 S.timeLimitMinutes = timeLimitMinutes;

 fetch('/session/curriculum/generate-exam', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 session_id: sessionId,
 student_id: parseInt(S.studentId || 1),
 num_questions: numQuestions,
 timer_mode: timerMode,
 time_limit_minutes: timeLimitMinutes,
 socket_id: socket?.id || ''
 })
 })
 .then(r => r.json())
 .then(data => {
 if (data.success && data.job_id) {
 _startJobPolling(data.job_id);
 } else {
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 if (loadEl) loadEl.style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 showToast(' Test generation failed: ' + (data.error || 'Server error'));
 }
 })
 .catch(err => {
 console.error('[Exam Gen Error]', err);
 if (_testLoadingTimerInterval) { clearInterval(_testLoadingTimerInterval); _testLoadingTimerInterval = null; }
 if (loadEl) loadEl.style.display = 'none';
 document.getElementById('testSetup').style.display = 'block';
 showToast('Error generating test from session.');
 });
}

function deleteSavedSession(sessionId) {
 if (!confirm('Are you sure you want to delete this saved study session?\n\nNOTE: All your past test attempts, test scores, and analytics will be permanently preserved.')) {
 return;
 }
 fetch(`/session/saved/${sessionId}`, { method: 'DELETE' })
 .then(r => r.json())
 .then(data => {
 showToast(' ' + (data.message || 'Session deleted.'));
 const card = document.getElementById(`savedCard_${sessionId}`);
 if (card) card.remove();
 })
 .catch(() => showToast('Error deleting session.'));
}

function answerCurriculumDrill(roundIdx, drillIdx, optIdx) {
 if (!S.currentCurriculum) return;
 const drill = S.currentCurriculum.rounds?.[roundIdx]?.practice_drills?.[drillIdx];
 if (!drill) return;

 const isCorrect = (optIdx === drill.correct_index);
 // Persist drill answer state on data model so switching tabs never resets it!
 drill.answered = true;
 drill.user_opt = optIdx;
 drill.is_correct = isCorrect;

 const fbEl = document.getElementById(`cDrillFeedback_${roundIdx}_${drillIdx}`);

 // Highlight selected option
 for (let i = 0; i < (drill.options || []).length; i++) {
 const btn = document.getElementById(`cDrill_${roundIdx}_${drillIdx}_${i}`);
 if (!btn) continue;
 btn.disabled = true;
 if (i === drill.correct_index) {
 btn.style.background = '#dcfce7';
 btn.style.borderColor = '#22c55e';
 btn.style.color = '#15803d';
 btn.innerHTML += ' <i class="bi bi-check-circle-fill" style="color:#16a34a"></i>';
 } else if (i === optIdx) {
 btn.style.background = '#fee2e2';
 btn.style.borderColor = '#ef4444';
 btn.style.color = '#b91c1c';
 btn.innerHTML += ' <i class="bi bi-x-circle-fill" style="color:#dc2626"></i>';
 }
 }

 if (fbEl) {
 fbEl.style.display = 'block';
 if (isCorrect) {
 fbEl.style.background = '#f0fdf4';
 fbEl.style.border = '1px solid #86efac';
 fbEl.style.color = '#166534';
 fbEl.innerHTML = `<strong> Correct! (+30 Knowledge Points)</strong><br/>${drill.explanation || ''}`;
 // Award knowledge points
 fetch('/session/verify-challenge', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 student_id : parseInt(S.studentId),
 session_id : S.sessionId,
 topic : S.currentCurriculum.topic,
 user_answer : drill.options[optIdx],
 correct_index: drill.correct_index,
 is_correct : true
 })
 }).then(() => refreshStats());
 } else {
 fbEl.style.background = '#fef2f2';
 fbEl.style.border = '1px solid #fca5a5';
 fbEl.style.color = '#991b1b';
 fbEl.innerHTML = `<strong>Incorrect.</strong> ${drill.explanation || ''}`;
 }
 }
}

function toggleCurriculumCheckpoint(roundIdx, chkIdx) {
 if (!S.currentCurriculum || !S.sessionId) return;
 const chk = S.currentCurriculum.rounds?.[roundIdx]?.active_checkpoints?.[chkIdx];
 if (!chk) return;
 chk.done = !chk.done;

 fetch('/session/curriculum/toggle-checkpoint', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 session_id: parseInt(S.sessionId),
 round_idx: parseInt(roundIdx),
 chk_idx: parseInt(chkIdx),
 student_id: parseInt(S.studentId || 1)
 })
 }).then(r => r.json()).then(d => {
 if (d.curriculum) {
 S.currentCurriculum = d.curriculum;
 renderCurriculumStudio(S.currentCurriculum, roundIdx);
 }
 refreshStats();
 }).catch(() => {});

 if (chk.done) {
 showToast(' Checkpoint accomplished (+15 KP)!');
 playChimeSound();
 triggerVibration([80]);
 }
 renderCurriculumStudio(S.currentCurriculum, roundIdx);
}

function syncActiveCurriculumDesktop(sessionId = null, topic = null, docName = null) {
 const sid = sessionId || S.sessionId || localStorage.getItem('session_id');
 const top = topic || document.getElementById('activeTopicName')?.textContent || 'Focus Study';
 const outEl = document.getElementById('studioOutput');

 if (!sid || sid === 'null' || !top || top === '—' || top === 'General Focus') {
 if (_curriculumAbortController) {
 try { _curriculumAbortController.abort(); } catch (e) {}
 _curriculumAbortController = null;
 }
 resetCurriculumBannerToIdle();
 if (outEl && outEl.innerHTML.includes('Curating Mastery Curriculum')) {
 outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }
 return;
 }

 const url = sid
 ? `/session/curriculum?session_id=${sid}&student_id=${S.studentId || 1}`
 : `/session/curriculum?student_id=${S.studentId || 1}`;

 fetch(url)
 .then(r => r.json())
 .then(d => {
 if (d.has_curriculum && d.curriculum) {
 S.sessionId = sid;
 localStorage.setItem('session_id', sid);
 S.currentCurriculum = d.curriculum;
 renderCurriculumStudio(d.curriculum, 0);
 startSprintFromCurriculum(0);
 } else if (sid && top && top !== 'General Focus') {
 S.sessionId = sid;
 localStorage.setItem('session_id', sid);

 if (_curriculumAbortController) {
 try { _curriculumAbortController.abort(); } catch (e) {}
 }
 _curriculumAbortController = new AbortController();
 const curSignal = _curriculumAbortController.signal;

 if (outEl) {
 outEl.style.display = 'block';
 outEl.innerHTML = `
 <div style="background:white;border:1px solid #e2e8f0;border-radius:12px;padding:28px 20px;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.04)">
 <div style="display:inline-flex;align-items:center;gap:8px;background:#eff6ff;color:#2563eb;padding:6px 16px;border-radius:20px;font-weight:800;font-size:0.8rem;margin-bottom:12px">
 <i class="bi bi-cpu-fill"></i> Autonomous AI Study Architect
 </div>
 <h3 style="font-size:1.2rem;color:#0f172a;margin-bottom:6px;font-weight:800">Curating Mastery Curriculum for: "${escapeHtml(top)}"</h3>
 <p style="font-size:0.82rem;color:#64748b;max-width:500px;margin:0 auto 20px;line-height:1.5">
 Retrieving authoritative academic knowledge and formulating Pomodoro stages...
 </p>
 <div style="display:flex;justify-content:center;gap:20px;flex-wrap:wrap;font-size:0.82rem;color:#334155;font-weight:700">
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Analyzing Concepts
 </div>
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Structuring Pomodoros
 </div>
 <div style="display:flex;align-items:center;gap:8px;background:#f8fafc;padding:8px 14px;border-radius:8px;border:1px solid #e2e8f0">
 <span class="spinner" style="display:inline-block;width:14px;height:14px;border-width:2px"></span> Formulating Drills
 </div>
 </div>
 </div>
 `;
 }
 fetch('/session/curriculum/generate', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic: top, student_id: parseInt(S.studentId || 1), session_id: parseInt(sid), doc_name: docName }),
 signal : curSignal
 })
 .then(r => r.json())
 .then(cData => {
 if (!S.sessionId || String(S.sessionId) !== String(sid) || curSignal.aborted) {
 console.log('[Curriculum Sync] Generation finished but session was ended. Discarding output.');
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 return;
 }
 if (cData.success && cData.curriculum) {
 S.sessionId = sid;
 localStorage.setItem('session_id', sid);
 S.currentCurriculum = cData.curriculum;
 renderCurriculumStudio(cData.curriculum, 0);
 startSprintFromCurriculum(0);
 showToast(`🎯 AI Curriculum ready & Sprint 1 started for "${top}"!`);
 } else {
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }
 })
 .catch(err => {
 if (err.name !== 'AbortError') {
 console.log('[Curriculum Sync Error]', err);
 }
 if (!S.sessionId) {
 resetCurriculumBannerToIdle();
 if (outEl) outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }
 });
 }
 })
 .catch(() => {});
}

function endSession() {
 if (_curriculumAbortController) {
 try { _curriculumAbortController.abort(); } catch (e) {}
 _curriculumAbortController = null;
 }
 const spinEl = document.getElementById('studioLoading');
 if (spinEl) spinEl.style.display = 'none';
 const outEl = document.getElementById('studioOutput');
 if (outEl) {
 outEl.style.display = 'block';
 outEl.classList.remove('raw-text');
 outEl.innerHTML = '<span class="empty-msg">Click an action above — output will appear here.</span>';
 }
 resetCurriculumBannerToIdle();

 const sid = S.sessionId || localStorage.getItem('session_id');
 S.sessionId = null;
 S.currentCurriculum = null;
 S.isSprintRunning = false;
 S.isSprintPaused = false;
 S.isBreakRunning = false;
 S.pomodoroRound = 0;
 localStorage.removeItem('session_id');

 // Reset Pomodoro counter at top left!
 const pCount = document.getElementById('pomodoroCount');
 if (pCount) pCount.textContent = '0';
 const pLbl = document.getElementById('pomodoroStatLbl');
 if (pLbl) pLbl.textContent = 'Pomodoros';
 updateRoundDots(0);

 const sStartPnl = document.getElementById('sessionStartPanel');
 if (sStartPnl) sStartPnl.style.display = 'block';
 const aInfo = document.getElementById('activeSessionInfo');
 if (aInfo) aInfo.style.display = 'none';
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = '—';

 const mList = document.getElementById('sessionMilestonesList');
 if (mList) mList.innerHTML = '<div style="font-size:0.75rem;color:var(--muted);text-align:center;padding:8px">No active study session.</div>';

 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'none';
 const examBtn = document.getElementById('btnExamFromSession');
 if (examBtn) examBtn.style.display = 'none';
 const sBtn = document.getElementById('startBtn');
 if (sBtn) { sBtn.style.display = 'inline-flex'; sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start'; }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const bBtn = document.getElementById('breakBtn');
 if (bBtn) bBtn.style.display = 'inline-flex';
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (cbBtn) cbBtn.style.display = 'none';

 const topInp = document.getElementById('topicInput');
 if (topInp) topInp.value = '';
 loadTodayPlans();
 loadUpcomingPlans();
 refreshStats();

 fetch('/session/end', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ session_id: sid ? parseInt(sid) : 0, student_id: parseInt(S.studentId || 1) })
 })
 .then(r => r.json())
 .then(() => {
 showToast('Session ended. Great focus!');
 })
 .catch(() => showToast('Session ended.'));
}

function startTimer() {
 if (!S.sessionId) {
 const topic = document.getElementById('topicInput')?.value.trim();
 if (!topic) {
 showToast(' Please enter a study topic below or choose a note from your library to begin.', 'info');
 const ti = document.getElementById('topicInput');
 if (ti) { ti.focus(); ti.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
 return;
 }
 prepareAndGenerateCurriculum(topic);
 return;
 }

 // If a studio curriculum exists, synchronize with the selected round!
 if (S.currentCurriculum && S.currentCurriculum.rounds && S.currentCurriculum.rounds.length > 0) {
 const curIdx = S.currentRoundIdx || 0;
 const rounds = S.currentCurriculum.rounds;
 const currentRound = rounds[curIdx] || rounds[0];
 const durMins = currentRound.suggested_duration_mins || 20;
 const roundTopic = `${S.currentCurriculum.topic} (R${currentRound.round_number}: ${currentRound.title})`;

 // If resuming the exact sprint that was paused:
 if (S.isSprintPaused && S.activeSprintRoundIdx === curIdx) {
 socket.emit('start_timer', {
 session_id : S.sessionId,
 student_id : S.studentId,
 is_break : false,
 duration_mins: durMins,
 topic : roundTopic,
 restart : false
 });
 S.isSprintRunning = true;
 S.isSprintPaused = false;
 document.getElementById('startBtn').style.display = 'none';
 document.getElementById('pauseBtn').style.display = 'inline-flex';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'inline-flex';
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) ctrl.innerHTML = renderCurriculumBannerButtons(curIdx, currentRound);
 playChimeSound();
 return;
 }

 // Otherwise, start this selected stage with its own exact duration!
 startSprintFromCurriculum(curIdx);
 return;
 }

 const curTopic = document.getElementById('activeTopicName')?.textContent || 'Focused Study';
 socket.emit('start_timer', { session_id: S.sessionId, student_id: S.studentId, is_break: false, topic: curTopic });
 S.isSprintRunning = true;
 S.isSprintPaused = false;
 document.getElementById('startBtn').style.display = 'none';
 document.getElementById('pauseBtn').style.display = 'inline-flex';
 const tEndBtn = document.getElementById('timerEndBtn');
 if (tEndBtn) tEndBtn.style.display = 'inline-flex';
 playChimeSound();
}

function stopTimer() {
 const sid = S.sessionId || localStorage.getItem('session_id');
 if (!sid) return;
 socket.emit('pause_timer', { session_id: sid });
 S.isSprintRunning = false;
 S.isSprintPaused = true;
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Resume';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 const ctrl = document.getElementById('curriculumBannerControls');
 if (ctrl) {
 const currentRound = S.currentCurriculum?.rounds?.[S.currentRoundIdx || 0] || {};
 ctrl.innerHTML = renderCurriculumBannerButtons(S.currentRoundIdx || 0, currentRound);
 }
}

function resetTimer() {
 if (!S.sessionId) return;
 socket.emit('reset_timer', { session_id: S.sessionId });
 document.getElementById('startBtn').style.display = 'inline-flex';
 document.getElementById('pauseBtn').style.display = 'none';
 document.getElementById('timerDisplay').textContent = '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
}

function startBreak() {
 if (!S.sessionId) { showToast(' Start a session first!'); return; }
 const curTopic = document.getElementById('activeTopicName')?.textContent || 'Break';
 socket.emit('start_timer', { session_id: S.sessionId, student_id: S.studentId, is_break: true, break_type: 'short', topic: curTopic });
 S.isBreakRunning = true;
 document.getElementById('startBtn').style.display = 'none';
 document.getElementById('pauseBtn').style.display = 'inline-flex';
 const bBtn = document.getElementById('breakBtn');
 if (bBtn) bBtn.style.display = 'none';
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (cbBtn) cbBtn.style.display = 'inline-flex';
 showToast(' Short break started (5m). Rest your eyes!');
}

function startLongBreak() {
 if (!S.sessionId) { showToast(' Start a session first!'); return; }
 const curTopic = document.getElementById('activeTopicName')?.textContent || 'Break';
 socket.emit('start_timer', { session_id: S.sessionId, student_id: S.studentId, is_break: true, break_type: 'long', topic: curTopic });
 S.isBreakRunning = true;
 document.getElementById('startBtn').style.display = 'none';
 document.getElementById('pauseBtn').style.display = 'inline-flex';
 const bBtn = document.getElementById('breakBtn');
 if (bBtn) bBtn.style.display = 'none';
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (cbBtn) cbBtn.style.display = 'inline-flex';
 showToast(' Long break started (15m). Walk around and recharge!');
}

function cancelBreak() {
 const sid = S.sessionId || localStorage.getItem('session_id');
 if (!sid) return;
 const curTopic = document.getElementById('activeTopicName')?.textContent || 'Focus Session';
 socket.emit('cancel_break', { session_id: sid, student_id: S.studentId, topic: curTopic, auto_start: true });
 S.isBreakRunning = false;
 S.isSprintRunning = true;
 S.isSprintPaused = false;
 const bBtn = document.getElementById('breakBtn');
 if (bBtn) bBtn.style.display = 'inline-flex';
 const cbBtn = document.getElementById('cancelBreakBtn');
 if (cbBtn) cbBtn.style.display = 'none';
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'inline-flex';
 const sBtn = document.getElementById('startBtn');
 if (sBtn) sBtn.style.display = 'none';
 showToast(' Break ended. Returning to study sprint!');
}

function updateRoundDots(r) {
 [1, 2, 3, 4].forEach(i => {
 const dot = document.getElementById(`rd${i}`);
 if (dot) dot.classList.toggle('filled', i <= r);
 });
}

function refreshStats() {
 const qCountEl = document.getElementById('questionCount');
 fetch(`/reports/overall?student_id=${S.studentId || 1}`)
 .then(r => r.json())
 .then(rep => {
 if (qCountEl && rep.history) {
 const totalQ = rep.history.reduce((sum, h) => sum + (h.total_questions || h.num_questions || 0), 0);
 qCountEl.textContent = totalQ;
 }
 })
 .catch(() => {});

 if (!S.sessionId) return;
 fetch(`/session/live-stats?session_id=${S.sessionId}&student_id=${S.studentId}`)
 .then(r => r.json())
 .then(data => {
 const e = document.getElementById('liveElapsed');
 const p = document.getElementById('livePace');
 const f = document.getElementById('liveFocus');
 const pm = document.getElementById('monElapsed');
 const pp = document.getElementById('monPace');
 if (e) e.textContent = data.elapsed_mins ? `${data.elapsed_mins}m active` : 'Session active';
 if (p) p.textContent = data.pace || 'Normal';
 if (f) f.textContent = data.focus_score ? `${data.focus_score}%` : '—';
 if (pm) pm.textContent = data.elapsed_mins ? `${data.elapsed_mins}m` : '0m';
 if (pp) pp.textContent = data.pace || '—';
 })
 .catch(() => {});
}

// ─────────────────────────────────────────
// Multi-Device Active Session Sync (Desktop)
// ─────────────────────────────────────────
function syncActiveSessionDesktop() {
 fetch('/session/active?student_id=' + (S.studentId || 1))
 .then(r => r.json())
 .then(d => {
 if (d.has_active) {
 S.sessionId = d.session_id;
 localStorage.setItem('session_id', S.sessionId);
 document.getElementById('sessionStartPanel').style.display = 'none';
 document.getElementById('activeSessionInfo').style.display = 'block';
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = d.topic;
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) {
 const mins = Math.floor(d.seconds_left / 60);
 const secs = d.seconds_left % 60;
 timerDisp.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
 }
 const prog = document.getElementById('timerProgress');
 if (prog) {
 prog.style.width = Math.round(((d.total_secs - d.seconds_left) / d.total_secs) * 100) + '%';
 }
 const lbl = document.getElementById('timerLabel');
 if (lbl) lbl.textContent = d.is_break ? (d.break_type === 'long' ? 'LONG BREAK' : 'SHORT BREAK') : 'FOCUS SESSION';
 if (d.running) {
 document.getElementById('startBtn').style.display = 'none';
 document.getElementById('pauseBtn').style.display = 'inline-flex';
 } else {
 document.getElementById('startBtn').style.display = 'inline-flex';
 document.getElementById('pauseBtn').style.display = 'none';
 }
 updateRoundDots(d.round || 1);
 if (d.milestones && d.milestones.length > 0) {
 renderDesktopMilestones(d.milestones);
 } else {
 fetchInteractiveMilestones(d.session_id, d.topic);
 }
 } else {
 const outEl = document.getElementById('studioOutput');
 if (_curriculumAbortController || (outEl && outEl.innerHTML.includes('Curating Mastery Curriculum'))) {
 return;
 }
 S.sessionId = null;
 localStorage.removeItem('session_id');
 const pnl = document.getElementById('sessionStartPanel');
 if (pnl) pnl.style.display = 'block';
 const act = document.getElementById('activeSessionInfo');
 if (act) act.style.display = 'none';
 const atn = document.getElementById('activeTopicName');
 if (atn) atn.textContent = '—';
 const timerDisp = document.getElementById('timerDisplay');
 if (timerDisp) timerDisp.textContent = '25:00';
 const prog = document.getElementById('timerProgress');
 if (prog) prog.style.width = '0%';
 const sBtn = document.getElementById('startBtn');
 if (sBtn) {
 sBtn.style.display = 'inline-flex';
 sBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
 }
 const pBtn = document.getElementById('pauseBtn');
 if (pBtn) pBtn.style.display = 'none';
 }
 })
 .catch(() => {});
}

// ─────────────────────────────────────────
// Interactive Sprint Milestones (Desktop)
// ─────────────────────────────────────────
function fetchInteractiveMilestones(sessionId, topic) {
 const container = document.getElementById('sessionMilestonesList');
 if (container) container.innerHTML = '<div style="font-size:0.75rem;color:var(--muted);text-align:center;padding:6px"><i class="bi bi-stars"></i> AI synthesizing study goals...</div>';

 fetch('/session/interactive-plan', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ session_id: sessionId, topic: topic, student_id: S.studentId || 1 })
 })
 .then(r => r.json())
 .then(d => {
 if (d.milestones) {
 renderDesktopMilestones(d.milestones);
 }
 })
 .catch(() => {
 if (container) container.innerHTML = '<div style="font-size:0.75rem;color:var(--muted)">1. Review definitions<br>2. Practice formulas<br>3. Test recall</div>';
 });
}

let _cachedDesktopMilestones = [];

function renderDesktopMilestones(milestones) {
 const container = document.getElementById('sessionMilestonesList');
 if (!container) return;
 if (milestones && Array.isArray(milestones)) {
 _cachedDesktopMilestones = milestones;
 } else {
 milestones = _cachedDesktopMilestones;
 }
 if (!milestones || milestones.length === 0) {
 container.innerHTML = '<div style="font-size:0.75rem;color:var(--muted);padding:4px">No milestones generated yet.</div>';
 return;
 }

 container.innerHTML = milestones.map((m, idx) => {
 const isCurrentStage = (S.currentRoundIdx === idx);
 const roundNumber = idx + 1;
 return `
 <div class="milestone-item ${m.done ? 'done' : ''} ${isCurrentStage ? 'active-sprint-stage' : ''}" 
 onclick="selectSprintFromMilestone(${idx})"
 style="cursor:pointer; transition:all 0.2s ease; ${isCurrentStage ? 'border-left: 3.5px solid #4f46e5 !important; background: #eef2ff !important;' : ''}"
 title="Click to view and start Sprint for Stage ${roundNumber}">
 <input type="checkbox" class="milestone-cb" ${m.done ? 'checked' : ''} onclick="event.stopPropagation(); toggleDesktopMilestone(${idx})" title="Check milestone (+15 KP)"/>
 <div class="milestone-content">
 <div class="milestone-title" style="${isCurrentStage ? 'font-weight:800;color:#3730a3;' : ''}">${escapeHtml(m.title)}</div>
 <div class="milestone-goal">${escapeHtml(m.goal || m.tip || '')}</div>
 </div>
 <span class="badge" style="font-size:0.65rem;padding:2px 6px;margin-left:auto;white-space:nowrap;border-radius:4px;font-weight:700;background:${isCurrentStage ? '#4f46e5' : '#f1f5f9'};color:${isCurrentStage ? '#fff' : '#64748b'}">
 ${isCurrentStage ? `R${roundNumber} Active` : `R${roundNumber}`}
 </span>
 </div>
 `;
 }).join('');
}

function selectSprintFromMilestone(stageIdx) {
 if (S.currentCurriculum) {
 switchCurriculumRound(stageIdx);
 const r = S.currentCurriculum.rounds?.[stageIdx] || {};
 showToast(` Switched to Stage ${stageIdx + 1}: ${r.title || 'Sprint'}`);
 }
}

function toggleDesktopMilestone(idx) {
 if (!S.sessionId) return;
 fetch('/session/toggle-milestone', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ session_id: S.sessionId, index: idx })
 })
 .then(r => r.json())
 .then(d => {
 if (d.milestones) {
 renderDesktopMilestones(d.milestones);
 showToast(' Milestone updated! Keep up the momentum.');
 playChimeSound();
 }
 });
}

// ─────────────────────────────────────────
// Quick Recall Challenge Modal (Desktop)
// ─────────────────────────────────────────
function triggerQuickChallenge() {
 const topic = document.getElementById('activeTopicName')?.textContent?.trim() || 'General';
 const modal = document.getElementById('challengeModal');
 const loading = document.getElementById('challengeLoading');
 const content = document.getElementById('challengeContent');
 const fb = document.getElementById('challengeFeedback');

 if (modal) modal.style.display = 'flex';
 if (loading) loading.style.display = 'block';
 if (content) content.style.display = 'none';
 if (fb) fb.style.display = 'none';

 fetch('/session/challenge', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ topic: topic, student_id: S.studentId || 1 })
 })
 .then(r => r.json())
 .then(d => {
 if (loading) loading.style.display = 'none';
 if (content) content.style.display = 'block';

 const ch = d.challenge;
 document.getElementById('challengeQuestionText').textContent = ch.question;
 const optsList = document.getElementById('challengeOptionsList');
 optsList.innerHTML = ch.options.map((opt, i) => `
 <button class="btn-outline" style="text-align:left;padding:10px 14px;font-size:0.88rem;border-radius:8px;font-weight:600"
 onclick="selectChallengeOption(${i}, ${ch.correct_index}, ${JSON.stringify(ch.explanation).replace(/"/g, '&quot;')})">
 <strong>${String.fromCharCode(65 + i)}.</strong> ${escapeHtml(opt)}
 </button>
 `).join('');
 })
 .catch(() => {
 if (loading) loading.innerHTML = '<div style="color:var(--danger)">Could not generate challenge question. Try again.</div>';
 });
}

function selectChallengeOption(selectedIdx, correctIdx, explanation) {
 const fb = document.getElementById('challengeFeedback');
 const opts = document.querySelectorAll('#challengeOptionsList button');
 opts.forEach((btn, i) => {
 btn.disabled = true;
 if (i === correctIdx) {
 btn.style.background = '#dcfce7';
 btn.style.borderColor = '#22c55e';
 btn.style.color = '#15803d';
 } else if (i === selectedIdx && selectedIdx !== correctIdx) {
 btn.style.background = '#fee2e2';
 btn.style.borderColor = '#ef4444';
 btn.style.color = '#b91c1c';
 }
 });

 fetch('/session/verify-challenge', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 session_id: S.sessionId,
 student_id: S.studentId || 1,
 selected_index: selectedIdx,
 correct_index: correctIdx,
 explanation: explanation
 })
 })
 .then(r => r.json())
 .then(d => {
 if (fb) {
 fb.style.display = 'block';
 fb.style.background = d.is_correct ? '#ecfdf5' : '#fffbeb';
 fb.style.border = `1px solid ${d.is_correct ? '#a7f3d0' : '#fde68a'}`;
 fb.style.color = d.is_correct ? '#065f46' : '#92400e';
 fb.innerHTML = `<strong>${d.is_correct ? ' Correct!' : ' Good Try!'}</strong> ${escapeHtml(d.message)}<br><span style="margin-top:4px;display:block">${escapeHtml(explanation)}</span>`;
 }
 if (d.is_correct) playChimeSound();
 refreshStats();
 });
}

function closeChallengeModal() {
 const modal = document.getElementById('challengeModal');
 if (modal) modal.style.display = 'none';
}

function askSessionClarify() {
 const inp = document.getElementById('sessionClarifyInput');
 const ansBox = document.getElementById('sessionClarifyAnswer');
 const q = inp ? inp.value.trim() : '';
 const topic = document.getElementById('activeTopicName')?.textContent?.trim() || 'General';

 if (!q) return;
 if (ansBox) {
 ansBox.style.display = 'block';
 ansBox.innerHTML = '<i class="bi bi-stars"></i> Consulting session notes...';
 }

 fetch('/session/clarify', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ question: q, topic: topic, session_id: S.sessionId, student_id: S.studentId || 1 })
 })
 .then(r => r.json())
 .then(d => {
 if (ansBox) {
 ansBox.innerHTML = `<strong>Tutor:</strong> ${escapeHtml(d.answer || 'No clarification available.')}`;
 }
 if (inp) inp.value = '';
 })
 .catch(() => {
 if (ansBox) ansBox.textContent = 'Could not generate answer.';
 });
}


// ─────────────────────────────────────────
// Documents Management
// ─────────────────────────────────────────
function loadDocuments() {
 fetch('/documents')
 .then(r => r.json())
 .then(data => {
 const docs = data.documents || [];
 const count = docs.length;

 // Update session monitor doc count & badges
 const ld = document.getElementById('liveDocs');
 if (ld) ld.textContent = `${count} docs`;
 const sc = document.getElementById('sourcesCount');
 if (sc) sc.textContent = count;
 const sb = document.getElementById('sourcesBadge');
 if (sb) sb.textContent = count;

 const label = document.getElementById('sourcesSelectedLabel');
 if (label && (!label.dataset.selected || label.dataset.selected === 'false')) {
 label.textContent = count ? `PDF Library (${count})` : 'No PDFs Uploaded';
 }

 // Populate sidebar session start Notes/PDF dropdown
 populateSessionDocSelect(docs);

 const list = document.getElementById('documentsList');
 if (!list) return;

 if (!docs.length) {
 list.innerHTML = '<div class="empty-msg" style="padding:14px 8px;text-align:center"><i class="bi bi-cloud-upload"></i><br>No PDFs uploaded yet.<br>Click "Add PDF" to upload.</div>';
 return;
 }

 list.innerHTML = docs.map(d => {
 const cleanName = d.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 const safeDoc = d.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
 return `
 <div class="doc-item" data-filename="${cleanName.toLowerCase()}">
 <div class="doc-main" onclick="selectDocForStudy('${safeDoc}')" title="Click to begin study session with this PDF: ${d}">
 <i class="bi bi-file-earmark-pdf-fill" style="color:#e63980;flex-shrink:0;font-size:0.95rem"></i>
 <span class="doc-title">${cleanName}</span>
 </div>
 <div class="doc-actions-row">
 <button class="doc-act-btn" onclick="event.stopPropagation(); generateDocSummary('${safeDoc}')" title="Generate AI Text Summary">
 <i class="bi bi-card-list"></i>
 </button>
 <button class="doc-act-btn" onclick="event.stopPropagation(); playDocAudio('${safeDoc}')" title="Play Audio Overview">
 <i class="bi bi-volume-up-fill"></i>
 </button>
 <button class="doc-act-btn doc-del-btn" onclick="event.stopPropagation(); deleteDoc('${safeDoc}')" title="Delete Document">
 <i class="bi bi-trash"></i>
 </button>
 </div>
 </div>
 `;
 }).join('');
 })
 .catch(err => console.error('[Docs] Load error:', err));
}

function populateSessionDocSelect(docsList = null) {
 const sSelect = document.getElementById('sessionDocSelect');
 if (!sSelect) return;
 const curVal = sSelect.value;

 const docsPromise = docsList !== null
 ? Promise.resolve(docsList)
 : fetch('/documents').then(r => r.json()).then(d => d.documents || []).catch(() => []);

 const savedPromise = fetch(`/session/saved-list?student_id=${S.studentId || 1}`)
 .then(r => r.json())
 .then(d => d.sessions || [])
 .catch(() => []);

 const notesPromise = fetch(`/notes?student_id=${S.studentId || 1}`)
 .then(r => r.json())
 .then(d => {
 if (d.notes && Array.isArray(d.notes)) {
 S.notes = d.notes;
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}
 }
 return S.notes || [];
 })
 .catch(() => S.notes || []);

 Promise.all([notesPromise, savedPromise, docsPromise]).then(([notes, saved, docs]) => {
 let html = '<option value="">-- Choose a Note or PDF Document --</option>';

 // 1. Personal Notes created in Quick Tools -> Notes
 if (notes && notes.length > 0) {
 html += '<optgroup label=" My Notes (Quick Tools)">';
 notes.forEach(n => {
 const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
 const title = n.title || (lines[0] ? lines[0].substring(0, 48) : 'Untitled Note');
 html += `<option value="my_note:${n.id}" data-topic="${escapeHtml(title)}"> ${escapeHtml(title)}</option>`;
 });
 html += '</optgroup>';
 }

 // 2. Saved Session Notes
 if (saved && saved.length > 0) {
 html += '<optgroup label=" Saved Study Notes">';
 saved.forEach(s => {
 const sTopic = s.topic || 'Session';
 html += `<option value="saved_session:${s.session_id}" data-topic="${escapeHtml(sTopic)}"> ${escapeHtml(sTopic)} (${s.rounds_count} Stages • Saved Notes)</option>`;
 });
 html += '</optgroup>';
 }

 // 3. Uploaded PDF Documents
 if (docs && docs.length > 0) {
 html += '<optgroup label=" Uploaded PDF Documents">';
 docs.forEach(d => {
 const clean = d.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 html += `<option value="${escapeHtml(d)}" data-topic="${escapeHtml(clean)}"> ${escapeHtml(clean)}</option>`;
 });
 html += '</optgroup>';
 }

 sSelect.innerHTML = html;
 if (curVal) sSelect.value = curVal;
 });
}

function toggleSourcesDropdown() {
 const wrapper = document.getElementById('sourcesDropdownWrapper');
 const menu = document.getElementById('sourcesDropdownMenu');
 if (!wrapper || !menu) return;

 const isOpen = wrapper.classList.toggle('open');
 menu.style.display = isOpen ? 'flex' : 'none';

 if (isOpen) {
 const inp = document.getElementById('sourcesSearchInput');
 if (inp) {
 inp.value = '';
 filterSourcesList('');
 inp.focus();
 }
 }
}

function filterSourcesList(query) {
 const q = (query || '').toLowerCase().trim();
 const items = document.querySelectorAll('#documentsList .doc-item');
 items.forEach(item => {
 const fn = item.getAttribute('data-filename') || item.textContent.toLowerCase();
 item.style.display = fn.includes(q) ? 'flex' : 'none';
 });
}

function initSourcesDropdownEvents() {
 document.addEventListener('click', e => {
 const wrapper = document.getElementById('sourcesDropdownWrapper');
 const menu = document.getElementById('sourcesDropdownMenu');
 if (wrapper && menu && !wrapper.contains(e.target)) {
 menu.style.display = 'none';
 wrapper.classList.remove('open');
 }
 });
}

function uploadPDF(event) {
 const file = event?.target?.files?.[0];
 if (!file) return;

 const MAX_SIZE = 100 * 1024 * 1024; // 100 MB limit
 if (file.size > MAX_SIZE) {
 showToast(' PDF file size exceeds the 100MB limit. Please upload a PDF under 100MB.');
 event.target.value = '';
 return;
 }

 const formData = new FormData();
 formData.append('file', file);
 formData.append('student_name', S.studentName);
 formData.append('topic', file.name.replace(/\.pdf$/i, ''));

 const msg = document.getElementById('uploadMsg');
 if (msg) { msg.style.display = 'block'; msg.textContent = `Uploading "${file.name}"...`; }
 showToast(`Uploading and indexing "${file.name}"...`);

 fetch('/upload-document/', { method: 'POST', body: formData })
 .then(r => {
 if (!r.ok) {
 return r.json().then(d => { throw new Error(d.error || `HTTP ${r.status}`); });
 }
 return r.json();
 })
 .then(data => {
 showToast(` ${data.message || 'Uploaded and indexed!'}`);
 if (msg) { msg.style.display = 'none'; }
 event.target.value = '';
 // Reload docs list
 setTimeout(loadDocuments, 500);
 })
 .catch(err => {
 console.error('[Upload error]', err);
 showToast(` ${err.message || 'Upload failed. Check server connection.'}`);
 if (msg) msg.style.display = 'none';
 });
}

function selectDocForStudy(docName) {
 const topic = docName.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 const ti = document.getElementById('topicInput');
 if (ti) ti.value = topic;

 const label = document.getElementById('sourcesSelectedLabel');
 if (label) {
 label.textContent = topic;
 label.dataset.selected = 'true';
 }

 // Close dropdown on select
 const wrapper = document.getElementById('sourcesDropdownWrapper');
 const menu = document.getElementById('sourcesDropdownMenu');
 if (wrapper && menu) {
 menu.style.display = 'none';
 wrapper.classList.remove('open');
 }

 // Also sync to test generator dropdown if available
 const testSel = document.getElementById('testDocSelect');
 if (testSel) {
 testSel.value = docName;
 if (testSel.value === docName) {
 onTestDocSelected();
 }
 }

 showToast(` Selected: "${topic}". Click "Begin Session" or "Generate Test"!`);
}

// ─────────────────────────────────────────
// AI Output Adjustability & View Presets
// ─────────────────────────────────────────
function toggleQuickActions() {
 const view = document.getElementById('view-home');
 const btnText = document.getElementById('toggleQuickActionsText');
 const btnIcon = document.getElementById('toggleQuickActionsIcon');
 if (!view) return;

 const isCollapsed = view.classList.toggle('action-cards-collapsed');
 if (btnText) btnText.textContent = isCollapsed ? 'Show Quick Actions' : 'Collapse Quick Actions';
 if (btnIcon) btnIcon.className = isCollapsed ? 'bi bi-grid' : 'bi bi-grid-fill';
}

function setStudioPreset(preset) {
 const view = document.getElementById('view-home');
 const studio = document.getElementById('studioSection');
 if (!view) return;

 // Clear previous classes
 view.classList.remove('studio-expanded', 'studio-focus-max', 'action-cards-collapsed');
 document.querySelectorAll('.btn-size-preset').forEach(b => b.classList.remove('active'));

 if (studio) {
 studio.style.flex = '';
 studio.style.height = '';
 }

 if (preset === 'expanded') {
 view.classList.add('studio-expanded');
 const b = document.getElementById('btnPresetExpanded');
 if (b) b.classList.add('active');
 } else if (preset === 'focus') {
 view.classList.add('studio-focus-max');
 const b = document.getElementById('btnPresetFocus');
 if (b) b.classList.add('active');
 } else {
 // Normal balanced
 const b = document.getElementById('btnPresetNormal');
 if (b) b.classList.add('active');
 }

 const fullIcon = document.getElementById('iconFullscreenStudio');
 const fullText = document.getElementById('textFullscreenStudio');
 if (preset === 'focus') {
 if (fullIcon) fullIcon.className = 'bi bi-fullscreen-exit';
 if (fullText) fullText.textContent = 'Restore';
 } else {
 if (fullIcon) fullIcon.className = 'bi bi-arrows-fullscreen';
 if (fullText) fullText.textContent = 'Maximize';
 }

 localStorage.setItem('studyedge_studio_preset', preset);
}

function toggleStudioFullscreen() {
 const view = document.getElementById('view-home');
 if (!view) return;
 const isFocus = view.classList.contains('studio-focus-max');
 setStudioPreset(isFocus ? 'normal' : 'focus');
}

function toggleTestFullscreen() {
 const testView = document.getElementById('view-test');
 const btn = document.getElementById('btnTestFullscreen');
 const icon = document.getElementById('iconTestFullscreen');
 const text = document.getElementById('textTestFullscreen');
 if (!testView) return;

 const isFull = testView.classList.toggle('fullscreen-test-mode');
 if (isFull) {
 if (icon) icon.className = 'bi bi-fullscreen-exit';
 if (text) text.textContent = 'Exit Fullscreen';
 if (btn) {
 btn.style.background = '#e0e7ff';
 btn.style.color = '#3730a3';
 btn.style.borderColor = '#a5b4fc';
 }
 try {
 if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
 document.documentElement.requestFullscreen().catch(() => {});
 }
 } catch (e) {}
 } else {
 if (icon) icon.className = 'bi bi-arrows-fullscreen';
 if (text) text.textContent = 'Fullscreen';
 if (btn) {
 btn.style.background = 'white';
 btn.style.color = '';
 btn.style.borderColor = '';
 }
 try {
 if (document.exitFullscreen && document.fullscreenElement) {
 document.exitFullscreen().catch(() => {});
 }
 } catch (e) {}
 }
}

function initStudioSplitter() {
 const splitter = document.getElementById('studioSplitter');
 const studio = document.getElementById('studioSection');
 const container = document.getElementById('view-home');
 if (!splitter || !studio || !container) return;

 let isDragging = false;
 let startY = 0;
 let startHeight = 0;

 splitter.addEventListener('mousedown', e => {
 isDragging = true;
 startY = e.clientY;
 startHeight = studio.getBoundingClientRect().height;
 splitter.classList.add('dragging');
 document.body.style.cursor = 'row-resize';
 document.body.style.userSelect = 'none';
 });

 window.addEventListener('mousemove', e => {
 if (!isDragging) return;
 const deltaY = startY - e.clientY;
 const newHeight = Math.max(160, Math.min(startHeight + deltaY, container.clientHeight - 80));
 studio.style.flex = 'none';
 studio.style.height = `${newHeight}px`;
 });

 window.addEventListener('mouseup', () => {
 if (!isDragging) return;
 isDragging = false;
 splitter.classList.remove('dragging');
 document.body.style.cursor = '';
 document.body.style.userSelect = '';
 localStorage.setItem('studyedge_custom_studio_height', studio.style.height);
 });

 const savedPreset = localStorage.getItem('studyedge_studio_preset') || 'normal';
 if (savedPreset !== 'normal') {
 setStudioPreset(savedPreset);
 } else {
 const savedH = localStorage.getItem('studyedge_custom_studio_height');
 if (savedH) {
 studio.style.flex = 'none';
 studio.style.height = savedH;
 }
 }
}

function deleteDoc(docName) {
 if (!confirm(`Delete "${docName}"?`)) return;
 fetch(`/delete-document/${encodeURIComponent(docName)}`, { method: 'DELETE' })
 .then(r => r.json())
 .then(data => { showToast(data.message || 'Deleted.'); loadDocuments(); })
 .catch(() => showToast('Delete failed.'));
}

// ─────────────────────────────────────────
// Study Planner (correct endpoints)
// ─────────────────────────────────────────
function getMinPlanDateTimeString() {
 const d = new Date();
 // Pad with leading zeros
 const pad = n => String(n).padStart(2, '0');
 const year = d.getFullYear();
 const month = pad(d.getMonth() + 1);
 const day = pad(d.getDate());
 const hours = pad(d.getHours());
 const mins = pad(d.getMinutes());
 return `${year}-${month}-${day}T${hours}:${mins}`;
}

function getMaxPlanDateTimeString() {
 const d = new Date();
 const pad = n => String(n).padStart(2, '0');
 const year = d.getFullYear() + 2; // Allow scheduling up to 2 years ahead
 const month = pad(d.getMonth() + 1);
 const day = pad(d.getDate());
 const hours = pad(d.getHours());
 const mins = pad(d.getMinutes());
 return `${year}-${month}-${day}T${hours}:${mins}`;
}

function initPlanDateTimeLimits() {
 const dtInput = document.getElementById('planDateTime');
 if (dtInput) {
 const minVal = getMinPlanDateTimeString();
 const maxVal = getMaxPlanDateTimeString();
 dtInput.min = minVal;
 dtInput.max = maxVal;
 }
}

function validatePlanDateTime(input) {
 if (!input || !input.value) return;
 const val = input.value;
 const parts = val.split('T');
 if (parts.length > 0) {
 const dateParts = parts[0].split('-');
 if (dateParts.length === 3) {
 const year = parseInt(dateParts[0], 10);
 const currentYear = new Date().getFullYear();
 if (dateParts[0].length > 4 || year > currentYear + 2 || year < currentYear) {
 showToast(` Year must be between ${currentYear} and ${currentYear + 2}.`);
 input.value = '';
 return;
 }
 }
 }

 const selected = new Date(val);
 const now = new Date();
 if (selected < now) {
 showToast(' Cannot schedule sessions in the past. Please select an upcoming date and time.');
 input.value = '';
 }
}

function createPlan() {
 const topic = document.getElementById('planTopic')?.value.trim();
 const dtInput = document.getElementById('planDateTime');
 const dt = dtInput?.value;
 const duration = parseInt(document.getElementById('planDuration')?.value) || 25;
 const notes = document.getElementById('planNotes')?.value.trim() || '';

 if (!topic || !dt) { showToast(' Enter a topic and date/time.'); return; }

 const selectedDate = new Date(dt);
 const now = new Date();
 const currentYear = now.getFullYear();

 // Validate 4-digit year limit
 if (selectedDate.getFullYear() > currentYear + 2 || selectedDate.getFullYear() < currentYear) {
 showToast(` Please choose a year between ${currentYear} and ${currentYear + 2}.`);
 if (dtInput) dtInput.focus();
 return;
 }

 // Validate past date/time limit
 if (selectedDate < now) {
 showToast(' Cannot schedule a session in the past. Choose a future time.');
 if (dtInput) dtInput.focus();
 return;
 }

 fetch('/plan/create', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 student_id : parseInt(S.studentId),
 topic,
 planned_start: dt,
 duration_mins: duration,
 notes
 })
 })
 .then(r => r.json().then(data => ({ status: r.status, body: data })))
 .then(res => {
 if (res.body.success) {
 showToast(' Study session scheduled!');
 document.getElementById('planTopic').value = '';
 if (dtInput) dtInput.value = '';
 document.getElementById('planNotes').value = '';
 loadTodayPlans();
 loadUpcomingPlans();
 } else {
 showToast(' ' + (res.body.error || 'Could not schedule session.'));
 }
 })
 .catch(() => showToast('Could not save plan.'));
}

function loadTodayPlans() {
 fetch(`/plan/today?student_id=${S.studentId}`)
 .then(r => r.json())
 .then(data => {
 const el = document.getElementById('todayPlansList');
 if (!el) return;
 const plans = data.plans || [];
 el.innerHTML = plans.length
 ? plans.map(p => renderPlanCard(p)).join('')
 : '<div class="empty-msg">No sessions planned for today.</div>';
 })
 .catch(() => {});
}

function loadUpcomingPlans() {
 fetch(`/plan/upcoming?student_id=${S.studentId}&days=7`)
 .then(r => r.json())
 .then(data => {
 const el = document.getElementById('upcomingPlansList');
 if (!el) return;
 const plans = data.plans || [];
 el.innerHTML = plans.length
 ? plans.map(p => renderPlanCard(p)).join('')
 : '<div class="empty-msg">No upcoming sessions.</div>';
 })
 .catch(() => {});
}

function renderPlanCard(plan) {
 const dtStr = new Date(plan.planned_start).toLocaleString([], {
 month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
 });
 const isActive = plan.status === 'active' || (S.sessionId && plan.topic === document.getElementById('activeTopicName')?.textContent);
 const isDone = plan.status === 'completed';
 const statusColor = isDone ? 'var(--success)' : isActive ? 'var(--warning)' : 'var(--muted)';
 const statusLabel = isDone ? 'Completed' : isActive ? 'Active Now' : 'Scheduled';
 const safeTopic = (plan.topic || 'Study Session').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');

 return `
 <div class="plan-item ${isActive ? 'active' : plan.status}" style="${isActive ? 'border: 1.5px solid var(--warning); box-shadow: 0 4px 14px rgba(245,158,11,0.18);' : ''}">
 <div class="plan-topic"><i class="bi bi-journal-bookmark-fill" style="color:${isActive ? 'var(--warning)' : 'var(--primary)'}"></i> ${escapeHtml(plan.topic)}</div>
 <div class="plan-meta">
 <span><i class="bi bi-clock"></i> ${dtStr}</span>
 <span><i class="bi bi-hourglass-split"></i> ${plan.duration_mins || plan.planned_duration_mins || 25} min</span>
 <span style="color:${statusColor};font-weight:700">${statusLabel}</span>
 </div>
 ${plan.notes ? `<div class="plan-notes">${escapeHtml(plan.notes)}</div>` : ''}
 <div class="plan-actions">
 ${isActive ? `
 <button class="btn-primary" style="padding:5px 12px;font-size:0.78rem;background:#059669;border-color:#059669"
 onclick="setView('home')">
 <i class="bi bi-eye-fill"></i> View Studio
 </button>
 <button class="btn-outline" style="padding:5px 10px;font-size:0.78rem;color:#dc2626;border-color:#fca5a5"
 onclick="endSession()">
 <i class="bi bi-stop-circle-fill"></i> End Session
 </button>
 ` : isDone ? `
 <button class="btn-outline" style="padding:4px 8px;font-size:0.75rem;color:#059669;border-color:#a7f3d0"
 onclick="startPlanSession(${plan.id}, '${safeTopic}')">
 <i class="bi bi-arrow-repeat"></i> Re-study
 </button>
 <button class="btn-outline" style="padding:4px 8px;font-size:0.75rem"
 onclick="deletePlanById(${plan.id})">
 <i class="bi bi-trash"></i>
 </button>
 ` : `
 <button class="btn-primary" style="padding:4px 10px;font-size:0.75rem"
 onclick="startPlanSession(${plan.id}, '${safeTopic}')">
 <i class="bi bi-play-fill"></i> Start
 </button>
 <button class="btn-outline" style="padding:4px 8px;font-size:0.75rem"
 onclick="deletePlanById(${plan.id})">
 <i class="bi bi-trash"></i>
 </button>
 `}
 </div>
 </div>
 `;
}

function startPlanSession(planId, topic) {
 const ti = document.getElementById('topicInput');
 if (ti) ti.value = topic;
 setView('home');
 showToast(` Launching planned session: "${topic}"...`);
 prepareAndGenerateCurriculum(topic, planId, null, null, true);
}

function deletePlanById(planId) {
 fetch(`/plan/delete/${planId}`, { method: 'DELETE' })
 .then(r => r.json())
 .then(() => { showToast('Plan removed.'); loadTodayPlans(); loadUpcomingPlans(); })
 .catch(() => showToast('Could not delete plan.'));
}

// ─────────────────────────────────────────
// Daily Quote, Notes & Audio
// ─────────────────────────────────────────
function loadDailyQuote() {
 fetch('/quote/daily')
 .then(r => r.json())
 .then(data => {
 const q = document.getElementById('quoteText');
 const c = document.getElementById('dailyQuote');
 if (q && data.quote) {
 q.textContent = `"${data.quote}"`;
 if (c) c.style.display = 'block';
 }
 })
 .catch(() => {});
}

function toggleNotes() {
 const p = document.getElementById('notesPanel');
 const o = document.getElementById('notesOverlay');
 const show = p.style.display === 'none' || !p.style.display;
 p.style.display = show ? 'flex' : 'none';
 if (o) o.style.display = show ? 'block' : 'none';
 if (show) {
 fetch(`/notes?student_id=${S.studentId || 1}`)
 .then(r => r.json())
 .then(d => {
 if (d.notes && Array.isArray(d.notes)) {
 S.notes = d.notes;
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}
 }
 })
 .catch(() => {})
 .finally(() => {
 renderNotesList();
 populateSessionDocSelect();
 });
 }
}
function closeNotes() {
 const p = document.getElementById('notesPanel');
 const o = document.getElementById('notesOverlay');
 if (p) p.style.display = 'none';
 if (o) o.style.display = 'none';
}
function renderNotesList() {
 const el = document.getElementById('notesList');
 if (!el) return;
 el.innerHTML = S.notes && S.notes.length
 ? S.notes.map(n => {
 const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
 const title = n.title || (lines[0] ? lines[0].substring(0, 50) : 'Personal Note');
 return `
 <div class="note-item" onclick="openNote('${n.id}')" style="cursor:pointer;padding:10px 12px;border-bottom:1px solid #f1f5f9;transition:background 0.15s">
 <div style="display:flex;align-items:center;gap:6px;font-weight:700;font-size:0.84rem;color:#1e293b;margin-bottom:2px">
 <i class="bi bi-journal-text" style="color:var(--primary);flex-shrink:0"></i>
 <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(title)}</span>
 </div>
 <div style="font-size:0.75rem;color:#64748b;line-height:1.4">
 ${escapeHtml((n.content || '').substring(0, 80))}${(n.content || '').length > 80 ? '…' : ''}
 </div>
 </div>`;
 }).join('')
 : '<div class="empty-msg">No notes yet. Click New Note to add one.</div>';
}
function addNote() {
 S.currentNoteId = null;
 const ta = document.getElementById('noteTextarea');
 if (ta) ta.value = '';
 document.getElementById('notesList').style.display = 'none';
 document.getElementById('noteEditor').style.display = 'flex';
}
function openNote(id) {
 S.currentNoteId = id;
 const note = S.notes.find(n => String(n.id) === String(id));
 if (!note) return;
 document.getElementById('noteTextarea').value = note.content || '';
 document.getElementById('notesList').style.display = 'none';
 document.getElementById('noteEditor').style.display = 'flex';
}
function saveNote() {
 const content = document.getElementById('noteTextarea')?.value.trim();
 if (!content) return;
 const noteId = S.currentNoteId || Date.now().toString();
 const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
 const title = lines[0] ? lines[0].substring(0, 50) : 'Personal Note';

 if (S.currentNoteId) {
 S.notes = S.notes.map(n => String(n.id) === String(S.currentNoteId) ? { ...n, content, title } : n);
 } else {
 S.notes.unshift({ id: noteId, content, title });
 }
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}

 // Sync to backend storage
 fetch('/notes', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ student_id: parseInt(S.studentId || 1), id: noteId, content, title })
 }).catch(e => console.error('[Notes] Save sync error:', e));

 backToNotesList();
 populateSessionDocSelect();
 showToast(' Note saved & added to Session selection!');
}
function deleteNote() {
 if (!S.currentNoteId) return;
 const idToDelete = S.currentNoteId;
 S.notes = S.notes.filter(n => String(n.id) !== String(idToDelete));
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}

 // Sync delete to backend
 fetch(`/notes/${idToDelete}?student_id=${S.studentId || 1}`, { method: 'DELETE' })
 .catch(e => console.error('[Notes] Delete error:', e));

 backToNotesList();
 populateSessionDocSelect();
 showToast('Note deleted.');
}
function backToNotesList() {
 const ne = document.getElementById('noteEditor');
 const nl = document.getElementById('notesList');
 if (ne) ne.style.display = 'none';
 if (nl) nl.style.display = 'block';
 renderNotesList();
}
// ─────────────────────────────────────────
// Flexible Save AI Chat to Study Notes System
// ─────────────────────────────────────────
let saveNotesModalState = {
 mode: 'msg', // 'msg' or 'thread'
 msgIndex: null,
 activeQuestion: '',
 activeAnswer: ''
};

function openSaveChatNotesModal(mode = 'msg', msgIndex = null) {
 const modal = document.getElementById('chatSaveNotesModal');
 if (!modal) return;

 saveNotesModalState.mode = mode;
 saveNotesModalState.msgIndex = msgIndex;

 // 1. Identify active question & answer
 let question = '';
 let answer = '';

 if (mode === 'msg' && msgIndex !== null && currentChatMessages[msgIndex]) {
 answer = currentChatMessages[msgIndex].content || '';
 // Look backward for preceding user question
 for (let i = msgIndex - 1; i >= 0; i--) {
 if (currentChatMessages[i].sender === 'user') {
 question = currentChatMessages[i].content || '';
 break;
 }
 }
 } else {
 // If thread mode or no specific message index, find the latest question/answer
 for (let i = currentChatMessages.length - 1; i >= 0; i--) {
 if (!answer && currentChatMessages[i].sender === 'bot') {
 answer = currentChatMessages[i].content || '';
 }
 if (answer && currentChatMessages[i].sender === 'user') {
 question = currentChatMessages[i].content || '';
 break;
 }
 }
 }

 saveNotesModalState.activeQuestion = question;
 saveNotesModalState.activeAnswer = answer;

 // 2. Select initial radio buttons based on trigger mode
 const pairRadio = document.getElementById('saveScopePair');
 const answerRadio = document.getElementById('saveScopeAnswer');
 const threadRadio = document.getElementById('saveScopeThread');

 if (mode === 'thread') {
 if (threadRadio) threadRadio.checked = true;
 } else {
 if (question && pairRadio) {
 pairRadio.checked = true;
 } else if (answerRadio) {
 answerRadio.checked = true;
 }
 }

 // Target default: if student has existing notes, select Append by default; otherwise New
 const targetAppend = document.getElementById('saveTargetAppend');
 const targetNew = document.getElementById('saveTargetNew');
 const hasExistingNotes = S.notes && S.notes.length > 0;

 if (hasExistingNotes && targetAppend) {
 targetAppend.checked = true;
 } else if (targetNew) {
 targetNew.checked = true;
 }

 // 3. Populate existing notes dropdown
 populateSaveNotesExistingSelect();

 // 4. Update UI visibility and compile note text
 onSaveNotesTargetChange();
 onSaveNotesScopeChange();

 modal.style.display = 'flex';
}

function closeSaveChatNotesModal() {
 const modal = document.getElementById('chatSaveNotesModal');
 if (modal) modal.style.display = 'none';
}

function populateSaveNotesExistingSelect() {
 const select = document.getElementById('saveNotesExistingSelect');
 if (!select) return;

 const notes = S.notes || [];
 if (notes.length === 0) {
 select.innerHTML = '<option value="">-- No existing notes found (Please Create New) --</option>';
 const targetNew = document.getElementById('saveTargetNew');
 if (targetNew) {
 targetNew.checked = true;
 onSaveNotesTargetChange();
 }
 return;
 }

 // Pre-select first note or previously matched thread note
 const currentThreadTitle = document.getElementById('chatActiveTitle')?.textContent?.trim() || '';
 let matchedIndex = 0;

 select.innerHTML = notes.map((n, idx) => {
 const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
 const title = n.title || (lines[0] ? lines[0].substring(0, 45) : `Note #${idx + 1}`);
 if (currentThreadTitle && title.toLowerCase().includes(currentThreadTitle.toLowerCase())) {
 matchedIndex = idx;
 }
 return `<option value="${escapeHtml(String(n.id))}">${escapeHtml(title)}</option>`;
 }).join('');

 if (select.options.length > matchedIndex) {
 select.selectedIndex = matchedIndex;
 }
}

function onSaveNotesTargetChange() {
 const isAppend = document.getElementById('saveTargetAppend')?.checked;
 const existingWrap = document.getElementById('saveNotesSelectExistingWrap');
 const titleWrap = document.getElementById('saveNotesTitleWrap');

 if (isAppend) {
 if (existingWrap) existingWrap.style.display = 'block';
 if (titleWrap) titleWrap.style.display = 'none';
 } else {
 if (existingWrap) existingWrap.style.display = 'none';
 if (titleWrap) titleWrap.style.display = 'block';

 // Suggest note title if empty
 const titleInp = document.getElementById('saveNotesTitleInput');
 if (titleInp && !titleInp.value) {
 const q = saveNotesModalState.activeQuestion;
 const threadTitle = document.getElementById('chatActiveTitle')?.textContent?.trim();
 if (threadTitle && threadTitle !== 'New Conversation') {
 titleInp.value = `${threadTitle} Notes`;
 } else if (q) {
 titleInp.value = q.substring(0, 45);
 } else {
 titleInp.value = 'Study Notes';
 }
 }
 }
}

function onSaveNotesScopeChange() {
 const scopePair = document.getElementById('saveScopePair')?.checked;
 const scopeAnswer = document.getElementById('saveScopeAnswer')?.checked;
 const scopeThread = document.getElementById('saveScopeThread')?.checked;

 const ta = document.getElementById('saveNotesPreviewTextarea');
 const titleInp = document.getElementById('saveNotesTitleInput');
 const threadTitle = document.getElementById('chatActiveTitle')?.textContent?.trim() || 'Study Session';

 let compiledText = '';
 let suggestedTitle = '';

 if (scopeAnswer) {
 compiledText = saveNotesModalState.activeAnswer || 'No response selected.';
 suggestedTitle = saveNotesModalState.activeQuestion ? saveNotesModalState.activeQuestion.substring(0, 45) : 'AI Study Note';
 } else if (scopePair) {
 const q = saveNotesModalState.activeQuestion || 'Question';
 const a = saveNotesModalState.activeAnswer || 'Answer';
 compiledText = `### Question:\n${q}\n\n### Answer:\n${a}`;
 suggestedTitle = q.substring(0, 45) || 'AI Q&A Note';
 } else if (scopeThread) {
 // Compile entire current conversation thread
 if (!currentChatMessages || currentChatMessages.length === 0) {
 compiledText = 'No messages in this conversation yet.';
 } else {
 const parts = [`# Study Notes: ${threadTitle}`, `*Compiled on ${new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}*\n`];
 
 let qNum = 1;
 for (let i = 0; i < currentChatMessages.length; i++) {
 const m = currentChatMessages[i];
 if (m.sender === 'user') {
 parts.push(`---\n### Question ${qNum++}:\n${m.content}`);
 } else if (m.sender === 'bot') {
 parts.push(`### Answer:\n${m.content}`);
 if (m.sources && m.sources.length > 0) {
 parts.push(`*Sources/References:* ${m.sources.map(s => s.title || s.url || s).join(', ')}`);
 }
 }
 }
 compiledText = parts.join('\n\n');
 }
 suggestedTitle = `${threadTitle} - Complete Guide`;
 }

 if (ta) ta.value = compiledText;
 if (titleInp && !titleInp.value) titleInp.value = suggestedTitle;
}

function confirmSaveChatNotes() {
 const content = document.getElementById('saveNotesPreviewTextarea')?.value?.trim();
 if (!content) {
 showToast(' Note content cannot be empty.', 'error');
 return;
 }

 const isAppend = document.getElementById('saveTargetAppend')?.checked;
 const nowStr = new Date().toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

 if (isAppend) {
 const select = document.getElementById('saveNotesExistingSelect');
 const noteId = select?.value;
 if (!noteId) {
 showToast(' Please select an existing note to append to.', 'error');
 return;
 }

 const note = S.notes.find(n => String(n.id) === String(noteId));
 if (!note) {
 showToast(' Selected note not found.', 'error');
 return;
 }

 // Append formatted content
 const updatedContent = `${note.content || ''}\n\n---\n*Added from AI Chat (${nowStr})*\n${content}`;
 note.content = updatedContent;
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}

 // Sync to backend
 fetch('/notes', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 student_id: parseInt(S.studentId || 1),
 id: String(noteId),
 content: updatedContent,
 title: note.title
 })
 }).catch(e => console.error('[Notes] Append sync error:', e));

 closeSaveChatNotesModal();
 populateSessionDocSelect();
 showToast(` Appended to "${note.title || 'Note'}" successfully!`, 'success');
 } else {
 // Create brand new note
 const titleInp = document.getElementById('saveNotesTitleInput');
 const rawTitle = titleInp?.value?.trim();
 const lines = content.split('\n').map(l => l.replace(/^[#* \t]+/, '').trim()).filter(Boolean);
 const title = rawTitle || (lines[0] ? lines[0].substring(0, 45) : 'AI Study Note');
 const noteId = Date.now().toString();

 S.notes.unshift({ id: noteId, content, title });
 try { localStorage.setItem('studyNotes', JSON.stringify(S.notes)); } catch (e) {}

 fetch('/notes', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 student_id: parseInt(S.studentId || 1),
 id: noteId,
 content: content,
 title: title
 })
 }).catch(e => console.error('[Notes] Create sync error:', e));

 closeSaveChatNotesModal();
 populateSessionDocSelect();
 showToast(` Created new note "${title}"!`, 'success');
 }

 // Refresh quick notes list if open
 if (typeof renderNotesList === 'function') {
 renderNotesList();
 }
}

function saveToNotes(text) {
 // Legacy fallback redirects directly to flexible modal
 saveNotesModalState.mode = 'msg';
 saveNotesModalState.activeAnswer = text;
 openSaveChatNotesModal('msg', null);
}

// ─────────────────────────────────────────
// ─────────────────────────────────────────
// Audio Overview & Voice Studio
// ─────────────────────────────────────────
let _availableSpeechVoices = [];
let _activeAudioUtterance = null;
let _currentAudioTitle = '';
let _isAudioPaused = false;

function initAudioVoices() {
 if (!('speechSynthesis' in window)) return;
 const populate = () => {
 _availableSpeechVoices = window.speechSynthesis.getVoices() || [];
 const sel = document.getElementById('audioVoiceSelect');
 if (!sel || _availableSpeechVoices.length === 0) return;
 const currentVal = sel.value;
 sel.innerHTML = '';
 
 // Sort: 1) Local offline voices, 2) English voices, 3) Other languages
 const sorted = [..._availableSpeechVoices].sort((a, b) => {
 const aEn = (a.lang || '').toLowerCase().startsWith('en');
 const bEn = (b.lang || '').toLowerCase().startsWith('en');
 const aLocal = a.localService === true || !a.name.toLowerCase().includes('online');
 const bLocal = b.localService === true || !b.name.toLowerCase().includes('online');

 if (aLocal && !bLocal) return -1;
 if (!aLocal && bLocal) return 1;
 if (aEn && !bEn) return -1;
 if (!aEn && bEn) return 1;
 return a.name.localeCompare(b.name);
 });

 sorted.forEach((v, idx) => {
 const opt = document.createElement('option');
 opt.value = v.name;
 const isOffline = v.localService === true || !v.name.toLowerCase().includes('online');
 const tag = isOffline ? ' [Offline]' : '';
 const isDefault = (currentVal ? v.name === currentVal : (v.default || idx === 0));
 opt.textContent = `${v.name}${tag}`;
 if (isDefault) opt.selected = true;
 sel.appendChild(opt);
 });
 };

 populate();
 if (window.speechSynthesis.onvoiceschanged !== undefined) {
 window.speechSynthesis.onvoiceschanged = populate;
 }
}

function previewAudioVoice() {
 if (!('speechSynthesis' in window)) {
 showToast('Speech Synthesis is not supported in this browser.', 'warning');
 return;
 }
 window.speechSynthesis.cancel();

 const previewText = "Hello! This is a preview of the selected voice style. Your study summaries and notes will sound like this.";
 const utt = new SpeechSynthesisUtterance(previewText);

 // Apply user selected voice
 const voiceSelect = document.getElementById('audioVoiceSelect');
 if (voiceSelect && voiceSelect.value && _availableSpeechVoices.length > 0) {
 const chosen = _availableSpeechVoices.find(v => v.name === voiceSelect.value);
 if (chosen) utt.voice = chosen;
 }

 // Apply speed
 const speedSelect = document.getElementById('audioSpeedSelect');
 utt.rate = speedSelect ? parseFloat(speedSelect.value || '1.0') : 1.0;

 // Apply pitch
 const pitchSelect = document.getElementById('audioPitchSelect');
 utt.pitch = pitchSelect ? parseFloat(pitchSelect.value || '1.0') : 1.0;

 utt.onend = () => {
 showToast(' Voice preview finished.');
 };

 window.speechSynthesis.speak(utt);
 showToast(' Playing voice preview (100% offline)...');
}

function switchAudioTab(tab) {
 const docList = document.getElementById('audioDocList');
 const noteList = document.getElementById('audioNotesList');
 const tabDocs = document.getElementById('audioTabDocs');
 const tabNotes = document.getElementById('audioTabNotes');

 if (tab === 'docs') {
 if (docList) docList.style.setProperty('display', 'flex', 'important');
 if (noteList) noteList.style.setProperty('display', 'none', 'important');
 if (tabDocs) tabDocs.classList.add('active');
 if (tabNotes) tabNotes.classList.remove('active');
 } else {
 if (docList) docList.style.setProperty('display', 'none', 'important');
 if (noteList) noteList.style.setProperty('display', 'flex', 'important');
 if (tabDocs) tabDocs.classList.remove('active');
 if (tabNotes) tabNotes.classList.add('active');
 }
}

function playAudioOverview() {
 initAudioVoices();
 const spin = document.getElementById('audioSpin');
 if (spin) spin.style.display = 'none';

 // 1. Fetch uploaded documents
 fetch('/documents')
 .then(r => r.json())
 .then(data => {
 const docs = data.documents || [];
 const dCount = document.getElementById('audioDocsCount');
 if (dCount) dCount.textContent = docs.length;

 const docList = document.getElementById('audioDocList');
 if (docList) {
 docList.innerHTML = docs.length
 ? docs.map(d => {
 const cleanTitle = d.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 return `
 <div class="audio-item-card" style="flex-shrink:0;min-height:54px" onclick="playDocAudio('${escapeHtml(d)}')">
 <div class="audio-item-left">
 <div class="audio-item-icon" style="background:#fdf2f8;color:#db2777">
 <i class="bi bi-file-earmark-pdf-fill"></i>
 </div>
 <div class="audio-item-info">
 <span class="audio-item-title" title="${escapeHtml(d)}">${escapeHtml(cleanTitle)}</span>
 <div class="audio-item-sub">PDF Document • Click to generate and play summary</div>
 </div>
 </div>
 <button class="btn-audio-listen">
 <i class="bi bi-play-circle-fill"></i> Listen
 </button>
 </div>`;
 }).join('')
 : '<p class="empty-msg" style="text-align:center;padding:16px">No PDF documents uploaded yet. Upload a document from the left panel.</p>';
 }
 })
 .catch(() => {});

 // 2. Populate study notes list
 const notes = S.notes || [];
 const nCount = document.getElementById('audioNotesCount');
 if (nCount) nCount.textContent = notes.length;

 const noteList = document.getElementById('audioNotesList');
 if (noteList) {
 noteList.innerHTML = notes.length
 ? notes.map(n => {
 const lines = (n.content || '').split('\n').map(l => l.trim()).filter(Boolean);
 const title = n.title || (lines[0] ? lines[0].substring(0, 50) : 'Personal Study Note');
 const snippet = (n.content || '').substring(0, 75).replace(/\n/g, ' ');
 return `
 <div class="audio-item-card" style="flex-shrink:0;min-height:54px" onclick="playNoteAudio('${escapeHtml(String(n.id))}')">
 <div class="audio-item-left">
 <div class="audio-item-icon" style="background:#eef2ff;color:#4f46e5">
 <i class="bi bi-journal-text"></i>
 </div>
 <div class="audio-item-info">
 <span class="audio-item-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
 <div class="audio-item-sub">${escapeHtml(snippet)}${snippet.length >= 75 ? '...' : ''}</div>
 </div>
 </div>
 <button class="btn-audio-listen">
 <i class="bi bi-play-circle-fill"></i> Listen
 </button>
 </div>`;
 }).join('')
 : '<p class="empty-msg" style="text-align:center;padding:16px">No study notes saved yet. Create a note from the Quick Tools panel.</p>';
 }

 // Set default tab to docs
 switchAudioTab('docs');

 const modal = document.getElementById('audioModal');
 if (modal) modal.style.display = 'flex';
}

function startSpeakingSummary(title, text) {
 if (!('speechSynthesis' in window)) {
 showToast('Speech Synthesis is not supported in this browser.', 'warning');
 return;
 }
 window.speechSynthesis.cancel();

 _activeAudioUtterance = new SpeechSynthesisUtterance(text);
 _currentAudioTitle = title;
 _isAudioPaused = false;

 // Apply user-selected voice
 const voiceSelect = document.getElementById('audioVoiceSelect');
 if (voiceSelect && voiceSelect.value && _availableSpeechVoices.length > 0) {
 const chosen = _availableSpeechVoices.find(v => v.name === voiceSelect.value);
 if (chosen) _activeAudioUtterance.voice = chosen;
 }

 // Apply speed / rate
 const speedSelect = document.getElementById('audioSpeedSelect');
 _activeAudioUtterance.rate = speedSelect ? parseFloat(speedSelect.value || '1.0') : 1.0;

 // Apply pitch
 const pitchSelect = document.getElementById('audioPitchSelect');
 _activeAudioUtterance.pitch = pitchSelect ? parseFloat(pitchSelect.value || '1.0') : 1.0;

 // Show active player widget
 const widget = document.getElementById('audioPlayerWidget');
 const pTitle = document.getElementById('audioPlayerTitle');
 const pIcon = document.getElementById('audioPlayerStatusIcon');
 const pauseBtnText = document.getElementById('btnAudioPauseText');
 const pauseBtnIcon = document.getElementById('btnAudioPauseIcon');

 if (widget) widget.style.display = 'block';
 if (pTitle) pTitle.textContent = title;
 if (pIcon) pIcon.className = 'bi bi-volume-up-fill';
 if (pauseBtnText) pauseBtnText.textContent = 'Pause';
 if (pauseBtnIcon) pauseBtnIcon.className = 'bi bi-pause-fill';

 _activeAudioUtterance.onend = () => {
 _isAudioPaused = false;
 if (widget) widget.style.display = 'none';
 showToast(' Audio playback completed.');
 };

 _activeAudioUtterance.onerror = (e) => {
 console.warn('[SpeechSynthesis Error]', e);
 _isAudioPaused = false;
 if (widget) widget.style.display = 'none';
 };

 window.speechSynthesis.speak(_activeAudioUtterance);
 showToast(` Speaking summary for "${title}"...`);
}

function playDocAudio(docName) {
 const spin = document.getElementById('audioSpin');
 const docList = document.getElementById('audioDocList');
 const noteList = document.getElementById('audioNotesList');

 if (spin) spin.style.display = 'block';
 if (docList) docList.style.display = 'none';
 if (noteList) noteList.style.display = 'none';

 const model = S.modelConfig.summary || 'mistral';
 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({ topic: docName, student_name: S.studentName, model })
 })
 .then(r => r.json())
 .then(data => {
 if (spin) spin.style.display = 'none';
 switchAudioTab('docs');
 const summaryText = data.summary || 'No summary available for this document.';
 const cleanTitle = docName.replace(/\.pdf$/i, '').replace(/_/g, ' ');
 startSpeakingSummary(cleanTitle, summaryText);
 })
 .catch(() => {
 if (spin) spin.style.display = 'none';
 switchAudioTab('docs');
 showToast(' Could not generate audio summary.');
 });
}

function playNoteAudio(noteId) {
 const note = (S.notes || []).find(n => String(n.id) === String(noteId));
 if (!note) {
 showToast(' Note not found.');
 return;
 }

 const spin = document.getElementById('audioSpin');
 const docList = document.getElementById('audioDocList');
 const noteList = document.getElementById('audioNotesList');

 if (spin) spin.style.display = 'block';
 if (docList) docList.style.display = 'none';
 if (noteList) noteList.style.display = 'none';

 const model = S.modelConfig.summary || 'mistral';
 fetch('/summary', {
 method : 'POST',
 headers: { 'Content-Type': 'application/json' },
 body : JSON.stringify({
 topic: note.title || 'Personal Study Note',
 student_name: S.studentName,
 model,
 note_content: note.content || ''
 })
 })
 .then(r => r.json())
 .then(data => {
 if (spin) spin.style.display = 'none';
 switchAudioTab('notes');
 const summaryText = data.summary || note.content || 'No content found in note.';
 startSpeakingSummary(note.title || 'Study Note', summaryText);
 })
 .catch(() => {
 if (spin) spin.style.display = 'none';
 switchAudioTab('notes');
 // Fallback directly speak raw note content
 startSpeakingSummary(note.title || 'Study Note', note.content || '');
 });
}

function toggleAudioPause() {
 if (!('speechSynthesis' in window)) return;
 const pauseBtnText = document.getElementById('btnAudioPauseText');
 const pauseBtnIcon = document.getElementById('btnAudioPauseIcon');
 const pIcon = document.getElementById('audioPlayerStatusIcon');

 if (_isAudioPaused) {
 window.speechSynthesis.resume();
 _isAudioPaused = false;
 if (pauseBtnText) pauseBtnText.textContent = 'Pause';
 if (pauseBtnIcon) pauseBtnIcon.className = 'bi bi-pause-fill';
 if (pIcon) pIcon.className = 'bi bi-volume-up-fill';
 showToast(' Resumed audio playback.');
 } else {
 window.speechSynthesis.pause();
 _isAudioPaused = true;
 if (pauseBtnText) pauseBtnText.textContent = 'Resume';
 if (pauseBtnIcon) pauseBtnIcon.className = 'bi bi-play-fill';
 if (pIcon) pIcon.className = 'bi bi-pause-circle';
 showToast(' Audio paused.');
 }
}

function stopAudioPlayback() {
 if ('speechSynthesis' in window) {
 window.speechSynthesis.cancel();
 }
 _isAudioPaused = false;
 const widget = document.getElementById('audioPlayerWidget');
 if (widget) widget.style.display = 'none';
 showToast(' Audio stopped.');
}

function speakText(btn) {
 const text = btn.dataset.text || '';
 if (S.isSpeaking) { window.speechSynthesis.cancel(); S.isSpeaking = false; return; }
 const utt = new SpeechSynthesisUtterance(text);
 utt.onend = () => { S.isSpeaking = false; };
 window.speechSynthesis.speak(utt);
 S.isSpeaking = true;
}

function closeAudioModal() {
 const m = document.getElementById('audioModal');
 if (m) m.style.display = 'none';
}

// ─────────────────────────────────────────
// Push Notifications
// ─────────────────────────────────────────

function openMobileModal() {
  const m = document.getElementById('mobileAppModal');
  if (m) m.style.display = 'flex';
  const urlEl = document.getElementById('mobileLanUrl');
  if (urlEl) {
    urlEl.textContent = `${window.location.protocol}//${window.location.host}/mobile`;
    fetch('/api/host-info')
      .then(r => r.json())
      .then(info => {
        if (info && info.all_ips && info.all_ips.length) {
          const ipsHtml = info.all_ips.map(ip => `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;background:white;padding:6px 10px;border-radius:6px;border:1px solid #cbd5e1;margin-bottom:4px">
              <span style="font-family:monospace;font-size:0.86rem;color:#1e293b;font-weight:700">http://${ip}:${info.port}/mobile</span>
              <button class="btn-outline" style="font-size:0.72rem;padding:3px 8px;border-radius:4px" onclick="navigator.clipboard.writeText('http://${ip}:${info.port}/mobile');showToast('📋 Copied address to clipboard!')">Copy</button>
            </div>
          `).join('');
          urlEl.innerHTML = `
            <div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;text-align:left">Available Network Addresses (Wi-Fi / Hotspot / LAN):</div>
            ${ipsHtml}
          `;
        }
      })
      .catch(() => {});
  }
}
function closeMobileModal() {
  const m = document.getElementById('mobileAppModal');
  if (m) m.style.display = 'none';
}

function enablePushNotifications() {
 const m = document.getElementById('pushModal');
 if (m) m.style.display = 'flex';
}
function closePushModal() {
 const m = document.getElementById('pushModal');
 if (m) m.style.display = 'none';
}

// ─────────────────────────────────────────
// Pause Reminders / Do Not Disturb (DND)
// ─────────────────────────────────────────
function openPauseRemindersModal() {
 const m = document.getElementById('pauseRemindersModal');
 if (m) m.style.display = 'flex';
 fetchRemindersStatus();
}

function closePauseRemindersModal() {
 const m = document.getElementById('pauseRemindersModal');
 if (m) m.style.display = 'none';
}

function fetchRemindersStatus() {
 const sid = S.studentId || localStorage.getItem('student_id') || '1';
 fetch(`/reminders/status?student_id=${sid}`)
 .then(r => r.json())
 .then(data => {
 if (data.success) {
 updateRemindersUI(data);
 }
 })
 .catch(() => {});
}

function pauseReminders(durationMins) {
 const sid = S.studentId || localStorage.getItem('student_id') || '1';
 fetch('/reminders/pause', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ student_id: parseInt(sid), duration_mins: durationMins })
 })
 .then(r => r.json())
 .then(data => {
 if (data.success) {
 updateRemindersUI(data);
 closePauseRemindersModal();
 const durText = durationMins === -1 ? 'indefinitely' : (durationMins >= 60 ? `${durationMins / 60}h` : `${durationMins}m`);
 showToast(` Reminders & alarms paused (${durText}). You will not be disturbed.`);
 }
 })
 .catch(err => {
 console.error('Error pausing reminders:', err);
 showToast(' Could not pause reminders.');
 });
}

function resumeReminders() {
 const sid = S.studentId || localStorage.getItem('student_id') || '1';
 fetch('/reminders/resume', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ student_id: parseInt(sid) })
 })
 .then(r => r.json())
 .then(data => {
 if (data.success) {
 updateRemindersUI(data);
 closePauseRemindersModal();
 showToast(' Reminders & alarms resumed! Notifications are active.');
 }
 })
 .catch(err => {
 console.error('Error resuming reminders:', err);
 showToast(' Could not resume reminders.');
 });
}

function updateRemindersUI(status) {
 S.remindersPaused = !!status.paused;
 const isPaused = S.remindersPaused;
 const remMins = status.remaining_minutes;

 // Persist locally for instant refresh synchronization
 if (isPaused) {
 localStorage.setItem('studyedge_reminders_paused', 'true');
 if (remMins !== undefined) localStorage.setItem('studyedge_reminders_mins', String(remMins));
 } else {
 localStorage.setItem('studyedge_reminders_paused', 'false');
 localStorage.removeItem('studyedge_reminders_mins');
 }

 // 1. Top Nav Button
 const navBtn = document.getElementById('navReminderToggleBtn');
 const navIcon = document.getElementById('navReminderIcon');
 const navText = document.getElementById('navReminderText');
 if (navBtn && navIcon && navText) {
 if (isPaused) {
 navBtn.style.background = '#fef2f2';
 navBtn.style.borderColor = '#fca5a5';
 navBtn.style.color = '#991b1b';
 navIcon.className = 'bi bi-bell-slash-fill';
 navIcon.style.color = '#ef4444';
 const timeStr = remMins === -1 ? 'Reminders Paused' : `Paused (${remMins}m)`;
 navText.textContent = timeStr;
 navBtn.title = 'Reminders are paused (Do Not Disturb). Click to resume or adjust.';
 } else {
 navBtn.style.background = '#f8fafc';
 navBtn.style.borderColor = '#cbd5e1';
 navBtn.style.color = '#475569';
 navIcon.className = 'bi bi-bell-fill';
 navIcon.style.color = '#059669';
 navText.textContent = 'Reminders Active';
 navBtn.title = 'Reminders are active. Click to pause if you are busy.';
 }
 }

 // 2. Right Panel Status Card
 const panelCard = document.getElementById('panelReminderStatusCard');
 const panelIcon = document.getElementById('panelReminderIcon');
 const panelLabel = document.getElementById('panelReminderLabel');
 const panelBtn = document.getElementById('panelReminderToggleBtn');
 const panelSub = document.getElementById('panelReminderSub');
 if (panelCard && panelIcon && panelLabel && panelBtn && panelSub) {
 if (isPaused) {
 panelCard.style.background = '#fef2f2';
 panelCard.style.borderColor = '#fecaca';
 panelIcon.className = 'bi bi-bell-slash-fill';
 panelIcon.style.color = '#ef4444';
 panelLabel.textContent = remMins === -1 ? 'Reminders: Paused' : `Reminders: Paused (${remMins}m)`;
 panelBtn.textContent = 'Resume';
 panelBtn.style.background = '#059669';
 panelBtn.style.color = 'white';
 panelBtn.style.borderColor = '#059669';
 panelBtn.onclick = resumeReminders;
 panelSub.textContent = 'Alarms and study reminders are currently silenced.';
 } else {
 panelCard.style.background = '#f8fafc';
 panelCard.style.borderColor = 'var(--border)';
 panelIcon.className = 'bi bi-bell-fill';
 panelIcon.style.color = '#059669';
 panelLabel.textContent = 'Reminders: Active';
 panelBtn.textContent = 'Pause';
 panelBtn.style.background = 'white';
 panelBtn.style.color = '';
 panelBtn.style.borderColor = '#cbd5e1';
 panelBtn.onclick = openPauseRemindersModal;
 panelSub.textContent = 'Alarms, study plan notifications & audio chimes are on.';
 }
 }

 // 3. Modal Active Banner
 const modalBanner = document.getElementById('pauseModalActiveBanner');
 const modalRemText = document.getElementById('pauseModalRemainingText');
 if (modalBanner) {
 modalBanner.style.display = isPaused ? 'block' : 'none';
 if (modalRemText && isPaused) {
 modalRemText.textContent = remMins === -1
 ? 'Reminders are paused indefinitely until you resume.'
 : `Reminders are paused. Will automatically resume in ~${remMins} minutes.`;
 }
 }
}

// ─────────────────────────────────────────
// Audio Chime & Mobile Haptic Vibration
// ─────────────────────────────────────────
function playChimeSound() {
 if (S.remindersPaused) {
 console.log('[Audio] Suppressed chime because reminders are paused (DND mode).');
 return;
 }
 try {
 const AudioContext = window.AudioContext || window.webkitAudioContext;
 if (!AudioContext) return;
 const ctx = new AudioContext();
 const now = ctx.currentTime;

 // First tone (523.25 Hz - C5)
 const osc1 = ctx.createOscillator();
 const gain1 = ctx.createGain();
 osc1.type = 'sine';
 osc1.frequency.setValueAtTime(523.25, now);
 gain1.gain.setValueAtTime(0.3, now);
 gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
 osc1.connect(gain1);
 gain1.connect(ctx.destination);
 osc1.start(now);
 osc1.stop(now + 0.5);

 // Second tone (659.25 Hz - E5)
 const osc2 = ctx.createOscillator();
 const gain2 = ctx.createGain();
 osc2.type = 'sine';
 osc2.frequency.setValueAtTime(659.25, now + 0.2);
 gain2.gain.setValueAtTime(0.35, now + 0.2);
 gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.8);
 osc2.connect(gain2);
 gain2.connect(ctx.destination);
 osc2.start(now + 0.2);
 osc2.stop(now + 0.8);
 } catch (e) {
 console.log('[Audio] AudioContext not permitted or supported yet:', e);
 }
}

function triggerVibration(pattern = [300, 150, 300, 150, 300]) {
 if (S.remindersPaused) return;
 try {
 if ('vibrate' in navigator) {
 navigator.vibrate(pattern);
 }
 } catch (e) {}
}

function urlB64ToUint8Array(base64String) {
 const padding = '='.repeat((4 - base64String.length % 4) % 4);
 const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
 const rawData = window.atob(base64);
 const outputArray = new Uint8Array(rawData.length);
 for (let i = 0; i < rawData.length; ++i) {
 outputArray[i] = rawData.charCodeAt(i);
 }
 return outputArray;
}

// ─────────────────────────────────────────
// In-App Reminders & Mobile Alert Polling
// ─────────────────────────────────────────
var _dismissedReminders = new Set();

function initReminderPolling() {
 checkReminders();
 setInterval(checkReminders, 45000);
}

function checkReminders() {
 const sid = S.studentId || 1;
 fetch(`/plan/reminders?student_id=${sid}&window=20`)
 .then(r => r.json())
 .then(data => {
 if (data.paused) {
 if (!S.remindersPaused) {
 S.remindersPaused = true;
 if (typeof updateRemindersUI === 'function') updateRemindersUI({ paused: true });
 }
 const existing = document.getElementById('reminderBanner');
 if (existing) existing.remove();
 return;
 }
 if (S.remindersPaused) return;
 const rems = data.reminders || [];
 if (rems.length === 0) return;

 // Find first reminder that wasn't dismissed
 const active = rems.find(r => !_dismissedReminders.has(r.id));
 if (active) {
 showReminderBanner(active);
 }
 })
 .catch(() => {});
}

function showReminderBanner(rem) {
 const existing = document.getElementById('reminderBanner');
 if (existing) existing.remove();

 playChimeSound();
 triggerVibration([400, 200, 400]);

 const banner = document.createElement('div');
 banner.id = 'reminderBanner';
 banner.className = 'reminder-slide-banner';
 const startStr = rem.planned_start ? rem.planned_start.slice(11, 16) : '';
 const timeMsg = rem.mins_until <= 0 ? 'Starting now!' : `starts in ${rem.mins_until} mins (${startStr})`;

 banner.innerHTML = `
 <div class="reminder-banner-content">
 <div class="reminder-icon-wrap">
 <i class="bi bi-alarm-fill text-warning"></i>
 </div>
 <div>
 <div class="reminder-banner-title">Upcoming Study Session!</div>
 <div class="reminder-banner-sub">"<strong>${escapeHtml(rem.topic)}</strong>" ${timeMsg}</div>
 </div>
 </div>
 <div class="reminder-banner-actions">
 <button class="btn-primary reminder-btn" onclick="startPlanSession(${rem.id}, '${escapeHtml(rem.topic).replace(/'/g, "\\'")}'); dismissReminder(${rem.id});">
 <i class="bi bi-play-fill"></i> Start Now
 </button>
 <button class="btn-outline reminder-btn" onclick="snoozeReminder(${rem.id})">
 Snooze 10m
 </button>
 <button class="reminder-close-btn" onclick="dismissReminder(${rem.id})" title="Dismiss">
 &times;
 </button>
 </div>
 `;

 document.body.appendChild(banner);
 setTimeout(() => banner.classList.add('visible'), 50);
}

function dismissReminder(remId) {
 if (remId) _dismissedReminders.add(remId);
 const banner = document.getElementById('reminderBanner');
 if (banner) {
 banner.classList.remove('visible');
 setTimeout(() => banner.remove(), 400);
 }
}

function snoozeReminder(remId) {
 dismissReminder(remId);
 showToast(' Reminder snoozed for 10 minutes.');
 setTimeout(() => {
 _dismissedReminders.delete(remId);
 checkReminders();
 }, 10 * 60 * 1000);
}

function testMobileAlert() {
 const sid = S.studentId || 1;
 fetch('/test-alert', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 student_id: parseInt(sid),
 title: ' StudyEdge Mobile Alert Test',
 body: 'Success! Your mobile study alerts are working perfectly.'
 })
 })
 .then(r => r.json())
 .then(data => {
 if (data.success) {
 showToast(' Test push notification sent to your device!');
 playChimeSound();
 triggerVibration();
 } else {
 showToast(data.error || 'Could not send test push.');
 }
 })
 .catch(() => showToast('Error sending test push alert.'));
}

async function requestPushPermission() {
 closePushModal();
 if (!('Notification' in window)) {
 showToast('Notifications not supported in this browser.');
 return;
 }

 try {
 const perm = await Notification.requestPermission();
 if (perm !== 'granted') {
 showToast(' Notification permission was not granted.');
 return;
 }

 let reg = null;
 if ('serviceWorker' in navigator) {
 reg = await navigator.serviceWorker.ready;
 }

 if (!reg || !('pushManager' in reg)) {
 localStorage.setItem('pushEnabled', 'true');
 const btn = document.getElementById('enablePushBtn');
 if (btn) { btn.innerHTML = '<i class="bi bi-bell-fill"></i> In-App Alerts Enabled'; btn.disabled = true; }
 showToast(' In-app notifications enabled!');
 playChimeSound();
 return;
 }

 // Fetch VAPID public key
 let pubKey = S.vapidPublicKey;
 if (!pubKey) {
 const resp = await fetch('/vapid-public-key');
 const d = await resp.json();
 pubKey = d.public_key;
 S.vapidPublicKey = pubKey;
 }

 if (!pubKey) {
 showToast('VAPID key not configured on server.');
 return;
 }

 const applicationServerKey = urlB64ToUint8Array(pubKey);
 const sub = await reg.pushManager.subscribe({
 userVisibleOnly: true,
 applicationServerKey
 });

 // Save subscription to backend local storage
 const subResp = await fetch('/subscribe', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 student_id: parseInt(S.studentId || 1),
 subscription: sub.toJSON()
 })
 });

 const resData = await subResp.json();
 if (resData.success) {
 localStorage.setItem('pushEnabled', 'true');
 const btn = document.getElementById('enablePushBtn');
 if (btn) {
 btn.innerHTML = '<i class="bi bi-bell-fill"></i> Mobile Alerts Active';
 btn.disabled = true;
 }
 showToast(' Mobile push alerts active on this device!');
 playChimeSound();
 triggerVibration();

 // Trigger instant verification alert
 setTimeout(() => testMobileAlert(), 1200);
 }
 } catch (err) {
 console.error('[PUSH ERROR]', err);
 localStorage.setItem('pushEnabled', 'true');
 showToast(' In-app alerts enabled! (Push: ' + (err.message || 'active') + ')');
 }
}


function renderRoundCompleteCard(topic, roundNum) {
 const liveStats = document.getElementById('liveStats');
 if (!liveStats) return;
 const existing = document.getElementById('postSessionTestPrompt');
 if (existing) existing.remove();

 const isCycleDone = (roundNum % 4 === 0);
 const div = document.createElement('div');
 div.id = 'postSessionTestPrompt';
 div.className = 'round-complete-card ' + (isCycleDone ? 'cycle-done' : '');

 if (isCycleDone) {
 div.innerHTML = `
 <div class="round-card-header">
 <span class="round-badge gold"><i class="bi bi-trophy-fill"></i> Full Cycle Complete!</span>
 <span class="round-sub">4 Pomodoros Done (100 mins focus)</span>
 </div>
 <p style="font-size:0.8rem;color:#475569;margin:8px 0">
 Outstanding endurance! You completed a full 4-round cycle on "<strong>${escapeHtml(topic)}</strong>". Take a well-deserved 15-minute long break or test your retention!
 </p>
 <div class="round-card-actions">
 <button class="btn-primary btn-sm" onclick="startLongBreak(); document.getElementById('postSessionTestPrompt').remove();">
 <i class="bi bi-cup-hot-fill"></i> Take 15m Long Break
 </button>
 <button class="btn-outline btn-sm" onclick="setView('test'); document.getElementById('postSessionTestPrompt').remove();">
 <i class="bi bi-patch-question-fill"></i> Test My Knowledge
 </button>
 </div>
 `;
 } else {
 div.innerHTML = `
 <div class="round-card-header">
 <span class="round-badge green"><i class="bi bi-check-circle-fill"></i> Round ${roundNum} of 4 Complete</span>
 <span class="round-sub">25 mins focused on "${escapeHtml(topic)}"</span>
 </div>
 <div class="round-card-actions">
 <button class="btn-primary btn-sm" onclick="startBreak(); document.getElementById('postSessionTestPrompt').remove();">
 <i class="bi bi-cup-straw"></i> 5m Short Break
 </button>
 <button class="btn-outline btn-sm" onclick="setView('test'); document.getElementById('postSessionTestPrompt').remove();">
 <i class="bi bi-journal-check"></i> Practice Quiz
 </button>
 <button class="btn-outline btn-sm" onclick="setView('chat'); document.getElementById('postSessionTestPrompt').remove();">
 <i class="bi bi-chat-dots-fill"></i> Ask AI
 </button>
 </div>
 `;
 }

 liveStats.prepend(div);
}
