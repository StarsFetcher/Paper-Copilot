/**
 * Paper-Copilot — Vue 3 Chat Application
 * ========================================
 * Uses Vue 3 + marked.js global builds from jsdelivr CDN.
 */

// Destructure Vue 3 global APIs
var createApp = Vue.createApp;
var ref = Vue.ref;
var computed = Vue.computed;
var watch = Vue.watch;
var nextTick = Vue.nextTick;
var onMounted = Vue.onMounted;

// ============================================================
// Marked.js Configuration
// ============================================================
if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true });
}

// ============================================================
// Helpers
// ============================================================

function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0;
        return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
}

function formatTime(ts) {
    if (!ts) return '';
    var now = Date.now();
    var diff = now - ts;
    var mins = Math.floor(diff / 60000);
    var hours = Math.floor(diff / 3600000);
    var days = Math.floor(diff / 86400000);
    if (mins < 1) return '刚刚';
    if (mins < 60) return mins + ' 分钟前';
    if (hours < 24) return hours + ' 小时前';
    if (days < 7) return days + ' 天前';
    var d = new Date(ts);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' +
           String(d.getHours()).padStart(2, '0') + ':' +
           String(d.getMinutes()).padStart(2, '0');
}

function truncate(str, maxLen) {
    maxLen = maxLen || 30;
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
            // Step 1: Protect LaTeX from markdown — collect all blocks sequentially
            var latexBlocks = [];

            var protected_ = text
                // Display math: $$...$$  or  \[...\]  or  [...\] (LLM pseudo-LaTeX)
                .replace(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\[\s*\\[^\]]*\])/g, function(m) {
                    latexBlocks.push({ raw: m, display: true });
                    return '%%LATEX_' + (latexBlocks.length - 1) + '%%';
                })
                // Inline math: $...$  or  \(...\)
                .replace(/(\$(?!\$)[^$\n]+?\$(?!\$)|\\\([\s\S]*?\\\))/g, function(m) {
                    latexBlocks.push({ raw: m, display: false });
                    return '%%LATEX_' + (latexBlocks.length - 1) + '%%';
                });

            // Step 2: Render markdown
            var html = marked.parse(protected_);

            // Step 3: Replace placeholders with KaTeX-rendered HTML
            for (var i = 0; i < latexBlocks.length; i++) {
                var block = latexBlocks[i];
                var raw = block.raw;

                // Strip delimiters to get pure formula
                var formula = raw
                    .replace(/^\$\$/, '').replace(/\$\$$/, '')   // $$...$$
                    .replace(/^\\\[/, '').replace(/\\\]$/, '')   // \[...\]
                    .replace(/^\[\s*\\/, '\\').replace(/\]$/, '')  // [...\] → \...
                    .replace(/^\\\(/, '').replace(/\\\)$/, '')   // \(...\)
                    .replace(/^\$/, '').replace(/\$$/, '');       // $...$

                var rendered;
                try {
                    if (typeof katex !== 'undefined') {
                        rendered = katex.renderToString(formula.trim(), {
                            displayMode: block.display,
                            throwOnError: false,
                            trust: true,
                        });
                    } else {
                        rendered = '<code>' + escapeHtml(formula) + '</code>';
                    }
                } catch (e) {
                    rendered = '<code>' + escapeHtml(formula) + '</code>';
                }

                html = html.split('%%LATEX_' + i + '%%').join(rendered);
            }

            return html;
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    } catch (e) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }
}

function highlightCodeBlocks(el) {
    if (!el || !window.hljs) return;
    el.querySelectorAll('pre code').forEach(function(block) {
        try { window.hljs.highlightElement(block); } catch (_) {}
    });
}

// ============================================================
// localStorage
// ============================================================

var STORAGE_KEY = 'paper-copilot-conversations';

function loadConversations() {
    try {
        var raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        var data = JSON.parse(raw);
        return Array.isArray(data) ? data : [];
    } catch (e) {
        return [];
    }
}

function saveConversations(conversations) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    } catch (e) {}
}

// ============================================================
// SSE Streaming
// ============================================================

function streamChat(query, searchMode, callbacks) {
    var controller = new AbortController();

    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query, stream: true, search_mode: searchMode }),
        signal: controller.signal,
    }).then(function(response) {
        if (!response.ok) {
            return response.text().then(function(t) {
                callbacks.onError('请求失败 (' + response.status + ')');
            });
        }

        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function pump() {
            reader.read().then(function(result) {
                if (result.done) {
                    callbacks.onDone();
                    return;
                }

                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.indexOf('data: ') !== 0) continue;

                    try {
                        var event = JSON.parse(line.substring(6));
                        switch (event.type) {
                            case 'token':
                                callbacks.onToken(event.content);
                                break;
                            case 'status':
                                callbacks.onStatus(event.content);
                                break;
                            case 'done':
                                callbacks.onDone();
                                return;
                            case 'error':
                                callbacks.onError(event.content || '未知错误');
                                return;
                        }
                    } catch (_) {}
                }

                pump();
            }).catch(function(err) {
                if (err.name === 'AbortError') {
                    callbacks.onDone();
                } else {
                    callbacks.onError('网络错误: ' + err.message);
                }
            });
        }

        pump();
    }).catch(function(err) {
        if (err.name === 'AbortError') {
            callbacks.onDone();
        } else {
            callbacks.onError('网络错误: ' + err.message);
        }
    });

    return controller;
}

// ============================================================
// Health Check
// ============================================================

function checkHealth() {
    return fetch('/api/health')
        .then(function(r) { return r.json(); })
        .then(function(d) { return d.code === 200; })
        .catch(function() { return false; });
}

// ============================================================
// Paper Count
// ============================================================

function fetchPaperCountApi() {
    return fetch('/api/stats')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.code === 200 && d.data) {
                return d.data.papers_count || 0;
            }
            return 0;
        })
        .catch(function() { return 0; });
}

// ============================================================
// PDF Upload (XHR with progress)
// ============================================================

function uploadFileToServer(file, onProgress, onSuccess, onError) {
    var xhr = new XMLHttpRequest();
    var formData = new FormData();
    formData.append('file', file);

    xhr.upload.addEventListener('progress', function(e) {
        if (e.lengthComputable) {
            var pct = Math.round((e.loaded / e.total) * 100);
            onProgress(pct);
        }
    });

    xhr.addEventListener('load', function() {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                var resp = JSON.parse(xhr.responseText);
                if (resp.code === 200) {
                    onSuccess(resp.data);
                } else {
                    onError(resp.message || '上传失败');
                }
            } catch (e) {
                onError('解析响应失败');
            }
        } else {
            onError('服务器错误: ' + xhr.status);
        }
    });

    xhr.addEventListener('error', function() {
        onError('网络错误，请检查服务是否运行');
    });

    xhr.open('POST', '/api/upload');
    xhr.send(formData);
}

// ============================================================
// Vue App
// ============================================================

var app = createApp({
    setup: function() {
        // --- State ---
        var conversations = ref(loadConversations());
        var activeConversationId = ref(null);
        var isStreaming = ref(false);
        var sidebarCollapsed = ref(false);
        var backendOnline = ref(false);
        var toast = ref({ message: '', type: 'success' });
        var showDeleteConfirm = ref(false);
        var pendingDeleteId = ref(null);
        var showClearAllConfirm = ref(false);
        var showUploadModal = ref(false);
        var paperCount = ref(0);
        var maxUploadSizeMB = ref(50);
        var uploadDragOver = ref(false);
        var uploadState = ref({
            status: 'idle',
            progress: 0,
            fileName: '',
            result: null,
            error: '',
        });
        var scanning = ref(false);

        // Context menu
        var ctxMenu = ref({ show: false, x: 0, y: 0, convId: null });

        // Rename
        var showRenameModal = ref(false);
        var renameValue = ref('');
        var renameTargetId = ref(null);
        var renameInput = ref(null);

        // Paper selector
        var showPaperSelect = ref(false);
        var papersList = ref([]);
        var papersLoading = ref(false);

        // Paper manager
        var showPaperManager = ref(false);
        var libPapers = ref([]);
        var libPapersLoading = ref(false);
        var selectedPaperIds = ref([]);
        var managerDeleting = ref(false);
        var pendingManagerDelete = ref(null);

        // Search mode: "auto" | "local" | "arxiv"
        var searchMode = ref("auto");

        var toastTimer = null;
        var streamController = null;

        // --- Computed ---
        var sortedConversations = computed(function() {
            return conversations.value.slice().sort(function(a, b) {
                return b.updatedAt - a.updatedAt;
            });
        });

        var activeConversation = computed(function() {
            if (!activeConversationId.value) return null;
            var list = conversations.value.filter(function(c) {
                return c.id === activeConversationId.value;
            });
            return list.length > 0 ? list[0] : null;
        });

        // selectedPapers from active conversation (for root template access)
        var selectedPapers = computed(function() {
            var conv = activeConversation.value;
            if (!conv || !conv.selectedPapers) return [];
            return conv.selectedPapers.slice(); // return copy for reactivity
        });

        // --- Persistence ---
        function persist() {
            saveConversations(conversations.value);
        }
        watch(conversations, persist, { deep: true });

        // --- Health ---
        function doHealthCheck() {
            checkHealth().then(function(ok) { backendOnline.value = ok; });
        }

        onMounted(function() {
            doHealthCheck();
            fetchPaperCount();
            if (sortedConversations.value.length > 0 && !activeConversationId.value) {
                activeConversationId.value = sortedConversations.value[0].id;
            }
            // Hide loading overlay
            var overlay = document.getElementById('loading-overlay');
            if (overlay) {
                overlay.style.opacity = '0';
                overlay.style.transition = 'opacity 0.3s';
                setTimeout(function() {
                    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
                }, 300);
            }
        });
        // Close context menu on any click outside
        document.addEventListener('click', function() {
            ctxMenu.value.show = false;
        });

        setInterval(doHealthCheck, 30000);

        // --- Toast ---
        function showToast(message, type) {
            type = type || 'success';
            if (toastTimer) clearTimeout(toastTimer);
            toast.value = { message: message, type: type };
            toastTimer = setTimeout(function() {
                toast.value = { message: '', type: 'success' };
            }, 3000);
        }

        // --- Conversations ---
        function createNewConversation() {
            if (isStreaming.value) {
                showToast('请等待回复完成', 'warning');
                return;
            }
            var c = {
                id: uuid(),
                title: '',
                messages: [],
                createdAt: Date.now(),
                updatedAt: Date.now(),
            };
            conversations.value.unshift(c);
            activeConversationId.value = c.id;
        }

        function selectConversation(id) {
            if (isStreaming.value) return;
            activeConversationId.value = id;
        }

        function requestDeleteConversation(id) {
            pendingDeleteId.value = id;
            showDeleteConfirm.value = true;
        }

        function confirmDelete() {
            var id = pendingDeleteId.value;
            conversations.value = conversations.value.filter(function(c) {
                return c.id !== id;
            });
            if (activeConversationId.value === id) {
                activeConversationId.value = conversations.value.length > 0
                    ? conversations.value[0].id : null;
            }
            showDeleteConfirm.value = false;
            pendingDeleteId.value = null;
        }

        // --- Batch Delete ---
        function clearAllConversations() {
            conversations.value = [];
            activeConversationId.value = null;
            showClearAllConfirm.value = false;
            persist();
            showToast('所有对话已清空', 'success');
        }

        // --- Context Menu ---
        function openCtxMenu(e, convId) {
            ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, convId: convId };
        }

        function deleteFromCtxMenu() {
            ctxMenu.value.show = false;
            if (ctxMenu.value.convId) {
                requestDeleteConversation(ctxMenu.value.convId);
            }
        }

        function renameFromCtxMenu() {
            var convId = ctxMenu.value.convId;
            ctxMenu.value.show = false;
            if (!convId) return;
            var conv = conversations.value.find(function(c) { return c.id === convId; });
            if (!conv) return;
            renameTargetId.value = convId;
            renameValue.value = conv.title || '';
            showRenameModal.value = true;
            // Focus input after modal renders
            nextTick(function() {
                var inp = document.querySelector('.rename-input');
                if (inp) { inp.focus(); inp.select(); }
            });
        }

        function confirmRename() {
            var name = renameValue.value.trim();
            if (!name || !renameTargetId.value) return;
            var conv = conversations.value.find(function(c) { return c.id === renameTargetId.value; });
            if (conv) {
                conv.title = name;
                conv.updatedAt = Date.now();
            }
            showRenameModal.value = false;
            renameTargetId.value = null;
            renameValue.value = '';
        }

        // --- Paper Selector ---
        function openPaperSelect() {
            showPaperSelect.value = true;
            fetchPapersList();
        }

        function fetchPapersList() {
            papersLoading.value = true;
            fetch('/api/papers')
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    console.log('[Papers] API response:', d);
                    if (d.code === 200 && d.data) {
                        papersList.value = d.data.papers || [];
                    } else {
                        papersList.value = [];
                    }
                    console.log('[Papers] List count:', papersList.value.length);
                })
                .catch(function(e) {
                    console.error('[Papers] Fetch error:', e);
                    papersList.value = [];
                })
                .finally(function() {
                    papersLoading.value = false;
                });
        }

        function togglePaper(name) {
            var conv = activeConversation.value;
            if (!conv) return;
            if (!conv.selectedPapers) conv.selectedPapers = [];
            var idx = conv.selectedPapers.indexOf(name);
            if (idx >= 0) {
                conv.selectedPapers.splice(idx, 1);
            } else {
                conv.selectedPapers.push(name);
            }
        }

        function confirmPaperSelect() {
            showPaperSelect.value = false;
        }

        function removePaper(name) {
            var conv = activeConversation.value;
            if (!conv || !conv.selectedPapers) return;
            var idx = conv.selectedPapers.indexOf(name);
            if (idx >= 0) conv.selectedPapers.splice(idx, 1);
        }

        // --- Paper Manager ---
        function openPaperManager() {
            showPaperManager.value = true;
            selectedPaperIds.value = [];
            pendingManagerDelete.value = null;
            fetchLibraryPapers();
        }

        function closePaperManager() {
            if (managerDeleting.value) return;
            showPaperManager.value = false;
            selectedPaperIds.value = [];
            pendingManagerDelete.value = null;
        }

        function fetchLibraryPapers() {
            libPapersLoading.value = true;
            fetch('/api/library/papers')
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.code === 200 && d.data) {
                        libPapers.value = d.data.papers || [];
                    } else {
                        libPapers.value = [];
                        showToast(d.message || '获取论文列表失败', 'error');
                    }
                })
                .catch(function(e) {
                    console.error('[Library] Fetch error:', e);
                    libPapers.value = [];
                    showToast('网络错误，无法获取论文列表', 'error');
                })
                .finally(function() {
                    libPapersLoading.value = false;
                });
        }

        function togglePaperManagerSelect(paperId) {
            var idx = selectedPaperIds.value.indexOf(paperId);
            if (idx >= 0) {
                selectedPaperIds.value.splice(idx, 1);
            } else {
                selectedPaperIds.value.push(paperId);
            }
        }

        function confirmDeleteManagerPaper(paperId, title) {
            pendingManagerDelete.value = { paper_id: paperId, title: title || paperId };
        }

        function cancelManagerDelete() {
            pendingManagerDelete.value = null;
        }

        function executeDeleteManagerPaper() {
            if (!pendingManagerDelete.value) return;
            var paperId = pendingManagerDelete.value.paper_id;
            pendingManagerDelete.value = null;
            deleteSinglePaper(paperId);
        }

        function deleteSinglePaper(paperId) {
            var encodedId = encodeURIComponent(paperId);
            managerDeleting.value = true;
            fetch('/api/library/papers/' + encodedId, { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.code === 200) {
                        showToast(d.message || '论文已删除', 'success');
                        libPapers.value = libPapers.value.filter(function(p) {
                            return p.paper_id !== paperId;
                        });
                        fetchPaperCount();
                    } else {
                        showToast(d.message || '删除失败', 'error');
                    }
                })
                .catch(function(e) {
                    console.error('[Delete] Error:', e);
                    showToast('网络错误，删除失败', 'error');
                })
                .finally(function() {
                    managerDeleting.value = false;
                });
        }

        function batchDeleteManagerPapers() {
            if (selectedPaperIds.value.length === 0) return;
            if (!confirm('确定要删除选中的 ' + selectedPaperIds.value.length + ' 篇论文吗？\n此操作将同时从向量索引中移除论文数据。')) {
                return;
            }
            managerDeleting.value = true;
            fetch('/api/library/papers/batch-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ paper_ids: selectedPaperIds.value, delete_files: true }),
            })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.code === 200) {
                        var msg = d.data.deleted + ' 篇已删除';
                        if (d.data.errors && d.data.errors.length > 0) {
                            msg += '，' + d.data.errors.length + ' 篇失败';
                        }
                        showToast(msg, 'success');
                        fetchLibraryPapers();
                        fetchPaperCount();
                        selectedPaperIds.value = [];
                    } else {
                        showToast(d.message || '批量删除失败', 'error');
                    }
                })
                .catch(function(e) {
                    console.error('[BatchDelete] Error:', e);
                    showToast('网络错误，批量删除失败', 'error');
                })
                .finally(function() {
                    managerDeleting.value = false;
                });
        }

        // --- Helpers ---
        function formatPaperName(name) {
            // Strip "papers/" prefix
            return name.replace(/^papers\//, '');
        }

        function formatSize(bytes) {
            if (!bytes) return '';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        }

        // --- Paper Count ---
        function fetchPaperCount() {
            fetchPaperCountApi().then(function(n) { paperCount.value = n; });
        }

        // --- Upload ---
        function openUploadModal() {
            resetUpload();
            showUploadModal.value = true;
        }

        function closeUploadModal() {
            showUploadModal.value = false;
            // Refresh paper count after upload
            if (uploadState.value.status === 'success') {
                fetchPaperCount();
            }
        }

        function resetUpload() {
            uploadState.value = {
                status: 'idle',
                progress: 0,
                fileName: '',
                result: null,
                error: '',
            };
        }

        function startUpload(file) {
            uploadState.value.status = 'uploading';
            uploadState.value.fileName = file.name;
            uploadState.value.progress = 0;

            uploadFileToServer(file,
                function(progress) {
                    uploadState.value.progress = progress;
                },
                function(data) {
                    uploadState.value.status = 'success';
                    uploadState.value.result = data;
                    uploadState.value.progress = 100;
                    showToast('论文入库成功: ' + data.file_name, 'success');
                },
                function(err) {
                    uploadState.value.status = 'error';
                    uploadState.value.error = err;
                    showToast(err, 'error');
                }
            );
        }

        function handleDrop(e) {
            uploadDragOver.value = false;
            var files = e.dataTransfer.files;
            if (files.length > 0) {
                validateAndUpload(files[0]);
            }
        }

        function handleFilePick(e) {
            var files = e.target.files;
            if (files.length > 0) {
                validateAndUpload(files[0]);
            }
        }

        function validateAndUpload(file) {
            if (uploadState.value.status === 'uploading') return;

            if (!file.name.toLowerCase().endsWith('.pdf')) {
                showToast('仅支持 PDF 格式文件', 'error');
                return;
            }

            var maxSize = maxUploadSizeMB.value * 1024 * 1024;
            if (file.size > maxSize) {
                showToast('文件过大，上限为 ' + maxUploadSizeMB.value + ' MB', 'error');
                return;
            }

            startUpload(file);
        }

        // --- Scan & Import (SSE streaming with progress) ---
        var showScanModal = ref(false);
        var scanProgress = ref({
            running: false, pct: 0, total: 0,
            scanned: 0, processed: 0, skipped: 0, errors: 0,
            message: '',
        });
        var scanLogs = ref([]);

        function addScanLog(text, cls) {
            scanLogs.value.push({ text: text, cls: cls || '' });
            // Keep last 200 lines
            if (scanLogs.value.length > 200) {
                scanLogs.value.splice(0, scanLogs.value.length - 200);
            }
            // Auto-scroll
            nextTick(function() {
                var el = document.querySelector('.scan-log');
                if (el) el.scrollTop = el.scrollHeight;
            });
        }

        function scanAndImport() {
            if (scanProgress.value.running) return;
            showScanModal.value = true;
            scanLogs.value = [];
            scanProgress.value = {
                running: true, pct: 0, total: 0,
                scanned: 0, processed: 0, skipped: 0, errors: 0,
                message: '正在收集文件列表…',
            };

            fetch('/api/scan?stream=true&force=false', { method: 'POST' })
                .then(function(response) {
                    if (!response.ok) {
                        scanProgress.value.running = false;
                        scanProgress.value.message = '请求失败 (' + response.status + ')';
                        addScanLog('扫描请求失败: HTTP ' + response.status, 'error');
                        return;
                    }
                    var reader = response.body.getReader();
                    var decoder = new TextDecoder();
                    var buffer = '';

                    function pump() {
                        reader.read().then(function(result) {
                            if (result.done) {
                                scanProgress.value.running = false;
                                fetchPaperCount();
                                return;
                            }
                            buffer += decoder.decode(result.value, { stream: true });
                            var lines = buffer.split('\n');
                            buffer = lines.pop() || '';
                            for (var i = 0; i < lines.length; i++) {
                                var line = lines[i].trim();
                                if (!line || line.indexOf('data: ') !== 0) continue;
                                try {
                                    var evt = JSON.parse(line.substring(6));
                                    switch (evt.type) {
                                        case 'start':
                                            scanProgress.value.total = evt.total;
                                            scanProgress.value.message = evt.message;
                                            scanProgress.value.pct = 0;
                                            addScanLog(evt.message, 'info');
                                            break;
                                        case 'skip':
                                            scanProgress.value.skipped = evt.skipped;
                                            scanProgress.value.processed = evt.processed;
                                            scanProgress.value.errors = evt.errors;
                                            scanProgress.value.scanned = evt.scanned;
                                            scanProgress.value.pct = evt.total > 0
                                                ? Math.round((evt.skipped + evt.processed + evt.errors) / evt.total * 100)
                                                : 0;
                                            scanProgress.value.message = evt.message;
                                            addScanLog(evt.file + ' — ' + evt.message, 'skip');
                                            break;
                                        case 'process':
                                            scanProgress.value.scanned = evt.scanned;
                                            scanProgress.value.pct = evt.total > 0
                                                ? Math.round((evt.skipped + evt.processed + evt.errors) / evt.total * 100)
                                                : 0;
                                            scanProgress.value.message = evt.message;
                                            addScanLog(evt.file + ' — ' + evt.message, 'process');
                                            break;
                                        case 'done':
                                            scanProgress.value.processed = evt.processed;
                                            scanProgress.value.scanned = evt.scanned;
                                            scanProgress.value.skipped = evt.skipped;
                                            scanProgress.value.errors = evt.errors;
                                            scanProgress.value.pct = evt.total > 0
                                                ? Math.round((evt.skipped + evt.processed + evt.errors) / evt.total * 100)
                                                : 0;
                                            scanProgress.value.message = evt.message;
                                            addScanLog(evt.file + ' — ' + evt.message, 'done');
                                            break;
                                        case 'error':
                                            scanProgress.value.errors = evt.errors;
                                            scanProgress.value.scanned = evt.scanned;
                                            scanProgress.value.pct = evt.total > 0
                                                ? Math.round((evt.skipped + evt.processed + evt.errors) / evt.total * 100)
                                                : 0;
                                            scanProgress.value.message = evt.message;
                                            addScanLog(evt.file + ' — ' + evt.message, 'error');
                                            break;
                                        case 'complete':
                                            scanProgress.value.running = false;
                                            scanProgress.value.processed = evt.processed;
                                            scanProgress.value.skipped = evt.skipped;
                                            scanProgress.value.errors = evt.errors;
                                            scanProgress.value.scanned = evt.scanned;
                                            scanProgress.value.pct = 100;
                                            scanProgress.value.message = evt.message;
                                            scanProgress.value.total = evt.total;
                                            addScanLog('━━━ ' + evt.message + ' ━━━', 'info');
                                            fetchPaperCount();
                                            break;
                                    }
                                } catch (_) {}
                            }
                            pump();
                        }).catch(function() {
                            scanProgress.value.running = false;
                            addScanLog('网络连接中断', 'error');
                        });
                    }
                    pump();
                })
                .catch(function(e) {
                    scanProgress.value.running = false;
                    scanProgress.value.message = '网络错误';
                    addScanLog('网络错误: ' + e.message, 'error');
                });
        }

        function closeScanModal() {
            if (scanProgress.value.running) return;
            showScanModal.value = false;
        }

        // --- Chat ---
        function handleSend(query) {
            if (!query || !query.trim() || isStreaming.value) return;

            var conv = activeConversation.value;
            if (!conv) {
                createNewConversation();
                conv = activeConversation.value;
            }
            if (!conv) return;

            var trimmed = query.trim();

            // Prepend selected papers to query context
            var papers = conv.selectedPapers;
            if (papers && papers.length > 0) {
                var paperNames = papers.map(function(n) { return formatPaperName(n); }).join(', ');
                trimmed = '[参考论文: ' + paperNames + '] ' + trimmed;
            }

            if (!conv.title) {
                conv.title = truncate(query.trim(), 30);
            }

            // Push user message (Vue makes it reactive via the array)
            conv.messages.push({
                role: 'user',
                content: trimmed,
                timestamp: Date.now(),
            });

            // Push assistant placeholder
            conv.messages.push({
                role: 'assistant',
                content: '',
                timestamp: Date.now(),
            });
            conv.updatedAt = Date.now();

            nextTick(function() { scrollToBottom(); });

            isStreaming.value = true;

            // --- CRITICAL: always read back from conv.messages (reactive array)
            //     never use a stale local variable that holds the raw object ---
            streamController = streamChat(trimmed, searchMode.value, {
                onToken: function(token) {
                    var msgs = conv.messages;
                    var lastMsg = msgs[msgs.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant') {
                        lastMsg.content += token;
                    }
                    conv.updatedAt = Date.now();
                    nextTick(function() { scrollToBottom(); });
                },
                onStatus: function(status) {
                    console.log('[Agent]', status);
                },
                onDone: function() {
                    isStreaming.value = false;
                    streamController = null;
                    var msgs = conv.messages;
                    var lastMsg = msgs[msgs.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.content.trim()) {
                        msgs.splice(msgs.length - 1, 1, {
                            role: 'assistant',
                            content: '抱歉，未能生成回复。请稍后重试。',
                            timestamp: Date.now(),
                        });
                    }
                    conv.updatedAt = Date.now();
                    nextTick(function() { scrollToBottom(); });
                },
                onError: function(err) {
                    isStreaming.value = false;
                    streamController = null;
                    var msgs = conv.messages;
                    var lastMsg = msgs[msgs.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant') {
                        if (!lastMsg.content.trim()) {
                            msgs.splice(msgs.length - 1, 1, {
                                role: 'assistant',
                                content: '⚠️ ' + err,
                                timestamp: Date.now(),
                            });
                        } else {
                            lastMsg.content += '\n\n⚠️ *' + err + '*';
                        }
                    }
                    showToast(err, 'error');
                    conv.updatedAt = Date.now();
                    nextTick(function() { scrollToBottom(); });
                },
            });
        }

        function handleStop() {
            if (streamController) {
                streamController.abort();
                streamController = null;
                isStreaming.value = false;
                showToast('已停止生成', 'warning');
            }
        }

        function scrollToBottom() {
            nextTick(function() {
                var areas = document.querySelectorAll('.messages-area');
                var area = areas[areas.length - 1];
                if (area) area.scrollTop = area.scrollHeight;
            });
        }

        // --- Expose ---
        return {
            conversations: conversations,
            activeConversationId: activeConversationId,
            isStreaming: isStreaming,
            sidebarCollapsed: sidebarCollapsed,
            backendOnline: backendOnline,
            toast: toast,
            showDeleteConfirm: showDeleteConfirm,
            showClearAllConfirm: showClearAllConfirm,
            showUploadModal: showUploadModal,
            paperCount: paperCount,
            maxUploadSizeMB: maxUploadSizeMB,
            uploadDragOver: uploadDragOver,
            uploadState: uploadState,
            ctxMenu: ctxMenu,
            showRenameModal: showRenameModal,
            renameValue: renameValue,
            renameInput: renameInput,
            showPaperSelect: showPaperSelect,
            papersList: papersList,
            papersLoading: papersLoading,
            searchMode: searchMode,

            sortedConversations: sortedConversations,
            activeConversation: activeConversation,
            selectedPapers: selectedPapers,

            createNewConversation: createNewConversation,
            selectConversation: selectConversation,
            requestDeleteConversation: requestDeleteConversation,
            confirmDelete: confirmDelete,
            clearAllConversations: clearAllConversations,
            openCtxMenu: openCtxMenu,
            deleteFromCtxMenu: deleteFromCtxMenu,
            renameFromCtxMenu: renameFromCtxMenu,
            confirmRename: confirmRename,
            openPaperSelect: openPaperSelect,
            togglePaper: togglePaper,
            confirmPaperSelect: confirmPaperSelect,
            removePaper: removePaper,
            // Paper Manager
            showPaperManager: showPaperManager,
            libPapers: libPapers,
            libPapersLoading: libPapersLoading,
            selectedPaperIds: selectedPaperIds,
            managerDeleting: managerDeleting,
            pendingManagerDelete: pendingManagerDelete,
            openPaperManager: openPaperManager,
            closePaperManager: closePaperManager,
            togglePaperManagerSelect: togglePaperManagerSelect,
            confirmDeleteManagerPaper: confirmDeleteManagerPaper,
            cancelManagerDelete: cancelManagerDelete,
            executeDeleteManagerPaper: executeDeleteManagerPaper,
            batchDeleteManagerPapers: batchDeleteManagerPapers,
            formatPaperName: formatPaperName,
            formatSize: formatSize,
            openUploadModal: openUploadModal,
            closeUploadModal: closeUploadModal,
            resetUpload: resetUpload,
            scanning: scanning,
            showScanModal: showScanModal,
            scanProgress: scanProgress,
            scanLogs: scanLogs,
            scanAndImport: scanAndImport,
            closeScanModal: closeScanModal,
            handleDrop: handleDrop,
            handleFilePick: handleFilePick,
            handleSend: handleSend,
            handleStop: handleStop,
            formatTime: formatTime,
        };
    },
});

// ============================================================
// Component: ChatView
// ============================================================
app.component('ChatView', {
    props: {
        conversation: Object,
        isStreaming: Boolean,
        selectedPapers: Array,
        searchMode: String,
    },
    emits: ['send', 'stop', 'open-paper-select', 'remove-paper', 'update:searchMode'],
    template: ''
        + '<div class="chat-view">'
        +   '<div class="chat-header">'
        +     '<span class="chat-header-title">{{ conversation.title || "新对话" }}</span>'
        +     '<div class="chat-header-actions">'
        +       '<span style="font-size:12px;color:var(--main-muted);">'
        +         '{{ conversation.messages.length }} 条消息'
        +       '</span>'
        +     '</div>'
        +   '</div>'
        +   '<div class="messages-area">'
        +     '<div class="messages-container">'
        +       '<div v-if="conversation.messages.length === 0" class="empty-state" style="padding:60px 20px;">'
        +         '<div class="empty-hero" style="padding:0;">'
        +           '<div class="hero-icon" style="font-size:48px;">\u{1F4AC}</div>'
        +           '<p style="color:var(--main-muted);">发送一条消息开始对话</p>'
        +         '</div>'
        +       '</div>'
        +       '<chat-message'
        +         ' v-for="(msg, idx) in conversation.messages"'
        +         ' :key="idx"'
        +         ' :message="msg"'
        +         ' :is-streaming="isStreaming && msg.role === \'assistant\' && idx === conversation.messages.length - 1"'
        +       '/>'
        +     '</div>'
        +   '</div>'
        +   '<div class="chat-input-area">'
        +     '<div class="paper-tags" v-if="selectedPapers && selectedPapers.length > 0">'
        +       '<span v-for="p in selectedPapers" :key="p" class="paper-tag">'
        +         '📄 {{ formatPaperNameShort(p) }}'
        +         '<span class="tag-remove" @click="$emit(\'remove-paper\', p)">&times;</span>'
        +       '</span>'
        +     '</div>'
        +     '<div class="search-mode-toggle">'
        +       '<button class="toggle-btn"'
        +         ' :class="{ active: searchMode === \'local\' }"'
        +         ' @click="$emit(\'update:searchMode\', searchMode === \'local\' ? \'auto\' : \'local\')"'
        +         ' title="仅从本地知识库检索"'
        +         ' :disabled="isStreaming">📂 本地检索</button>'
        +       '<button class="toggle-btn"'
        +         ' :class="{ active: searchMode === \'arxiv\' }"'
        +         ' @click="$emit(\'update:searchMode\', searchMode === \'arxiv\' ? \'auto\' : \'arxiv\')"'
        +         ' title="联网搜索 arXiv 论文"'
        +         ' :disabled="isStreaming">🌐 联网搜索</button>'
        +     '</div>'
        +     '<div class="input-container">'
        +       '<button class="btn-attach"'
        +         ' :class="{ \'has-selection\': selectedPapers && selectedPapers.length > 0 }"'
        +         ' @click="$emit(\'open-paper-select\')"'
        +         ' title="选择参考论文">'
        +         '📎'
        +       '</button>'
        +       '<textarea ref="textarea" class="chat-textarea"'
        +         ' :value="text"'
        +         ' rows="1"'
        +         ' :placeholder="isStreaming ? \'正在生成回复…\' : \'输入您的问题… (Enter 发送, Shift+Enter 换行)\'"'
        +         ' :disabled="isStreaming"'
        +         ' @keydown="onKeydown"'
        +         ' @input="onInput">'
        +       '</textarea>'
        +       '<button v-if="!isStreaming" class="btn-send" :disabled="!text.trim() || isStreaming" @click="doSend" title="发送">➤</button>'
        +       '<button v-else class="btn-send stop" @click="$emit(\'stop\')" title="停止生成">■</button>'
        +     '</div>'
        +   '</div>'
        + '</div>',
    data: function() {
        return { text: '' };
    },
    methods: {
        doSend: function() {
            var t = this.text.trim();
            if (!t || this.isStreaming) return;
            this.$emit('send', t);
            this.text = '';
        },
        onKeydown: function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.doSend();
            }
        },
        onInput: function(e) {
            this.text = e.target.value;
            var ta = e.target;
            ta.style.height = 'auto';
            ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
        },
        formatPaperNameShort: function(name) {
            return name.replace(/^papers\//, '').replace(/\.pdf$/i, '');
        },
    },
});

// ============================================================
// Component: ChatMessage
// ============================================================
app.component('ChatMessage', {
    props: {
        message: Object,
        isStreaming: Boolean,
    },
    computed: {
        renderedContent: function() {
            if (this.message.role === 'user') {
                return escapeHtml(this.message.content);
            }
            return renderMarkdown(this.message.content);
        },
        avatar: function() {
            return this.message.role === 'user' ? '\u{1F464}' : '\u{1F916}';
        },
    },
    methods: {
        formatTime: formatTime,
    },
    watch: {
        renderedContent: function() {
            var self = this;
            this.$nextTick(function() {
                if (self.$el) highlightCodeBlocks(self.$el);
            });
        },
    },
    mounted: function() {
        highlightCodeBlocks(this.$el);
    },
    updated: function() {
        highlightCodeBlocks(this.$el);
    },
    template: ''
        + '<div class="message-wrapper" :class="message.role">'
        +   '<div class="message-avatar">{{ avatar }}</div>'
        +   '<div style="flex:1;min-width:0;">'
        +     '<div class="message-bubble"'
        +       ' :class="{ \'streaming-cursor\': isStreaming && message.role === \'assistant\' }"'
        +       ' v-html="renderedContent">'
        +     '</div>'
        +     '<div class="message-time">{{ formatTime(message.timestamp) }}</div>'
        +   '</div>'
        + '</div>',
});

// ============================================================
// Component: ChatInput
// ============================================================
app.component('ChatInput', {
    props: {
        disabled: Boolean,
        isStreaming: Boolean,
    },
    emits: ['send', 'stop'],
    data: function() {
        return { text: '' };
    },
    methods: {
        handleSend: function() {
            var t = this.text.trim();
            if (!t || this.disabled) return;
            this.$emit('send', t);
            this.text = '';
            var self = this;
            this.$nextTick(function() {
                var ta = self.$refs.textarea;
                if (ta) ta.style.height = 'auto';
            });
        },
        handleStop: function() {
            this.$emit('stop');
        },
        onKeydown: function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            }
        },
        autoResize: function(e) {
            var ta = e.target;
            ta.style.height = 'auto';
            ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
        },
    },
    template: ''
        + '<div class="chat-input-area">'
        +   '<div class="input-container">'
        +     '<textarea ref="textarea" class="chat-textarea" v-model="text" rows="1"'
        +       ' :placeholder="disabled ? \'正在生成回复…\' : \'输入您的问题… (Enter 发送, Shift+Enter 换行)\'"'
        +       ' :disabled="disabled"'
        +       ' @keydown="onKeydown"'
        +       ' @input="autoResize">'
        +     '</textarea>'
        +     '<button v-if="!isStreaming" class="btn-send" :disabled="!text.trim() || disabled" @click="handleSend" title="发送">➤</button>'
        +     '<button v-else class="btn-send stop" @click="handleStop" title="停止生成">■</button>'
        +   '</div>'
        + '</div>',
});

// ============================================================
// Mount
// ============================================================
app.mount('#app');
