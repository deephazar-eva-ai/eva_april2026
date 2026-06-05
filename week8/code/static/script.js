document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('queryForm');
    const input = document.getElementById('queryInput');
    const submitBtn = document.getElementById('submitBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const spinner = submitBtn.querySelector('.spinner');
    
    const nodeTracker = document.getElementById('nodeTracker');
    const terminalLogs = document.getElementById('terminalLogs');
    const resultContent = document.getElementById('resultContent');
    const executionStatus = document.getElementById('executionStatus');

    let nodes = new Map();
    let eventSource = null;

    // Setup Marked.js with highlight.js
    marked.setOptions({
        highlight: function(code, lang) {
            const language = hljs.getLanguage(lang) ? lang : 'plaintext';
            return hljs.highlight(code, { language }).value;
        },
        langPrefix: 'hljs language-'
    });

    function setUIState(running) {
        input.disabled = running;
        submitBtn.disabled = running;
        if (running) {
            btnText.classList.add('hidden');
            spinner.classList.remove('hidden');
            executionStatus.textContent = 'Running';
            executionStatus.className = 'status-badge running';
            nodeTracker.innerHTML = '';
            terminalLogs.innerHTML = '';
            resultContent.innerHTML = '<div class="empty-state">Waiting for final output...</div>';
            nodes.clear();
        } else {
            btnText.classList.remove('hidden');
            spinner.classList.add('hidden');
            if (executionStatus.textContent === 'Running') {
                executionStatus.textContent = 'Complete';
                executionStatus.className = 'status-badge success';
            }
        }
    }

    function appendLog(msg, type = 'info') {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        line.textContent = msg;
        terminalLogs.appendChild(line);
        terminalLogs.scrollTop = terminalLogs.scrollHeight;
    }

    function updateNode(nodeId, skill, status, elapsed_s, iteration) {
        let nodeEl = document.getElementById(`node-${nodeId}`);
        
        let timeText = elapsed_s !== undefined ? `(${elapsed_s.toFixed(1)}s)` : '';
        let iterText = iteration !== undefined ? `<span class="node-id" style="margin-left: 0.5rem; background: rgba(99, 102, 241, 0.2); color: var(--accent-primary)">Iter ${iteration}</span>` : '';

        if (!nodeEl) {
            nodeEl = document.createElement('div');
            nodeEl.id = `node-${nodeId}`;
            nodeEl.className = 'node-item';
            nodeTracker.appendChild(nodeEl);
        }

        nodeEl.innerHTML = `
            <div class="node-info">
                <div class="node-status ${status}"></div>
                <span class="node-id">${nodeId}</span>
                <span class="node-skill">${skill}</span>
                ${iterText}
            </div>
            <div class="node-status-text">
                ${status} <span style="opacity: 0.7; font-size: 0.85em; margin-left: 0.5rem">${timeText}</span>
            </div>
        `;
        
        // Scroll to bottom
        nodeTracker.scrollTop = nodeTracker.scrollHeight;
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = input.value.trim();
        if (!query) return;

        if (eventSource) {
            eventSource.close();
        }

        setUIState(true);
        appendLog(`> Starting execution for query: "${query}"`);

        const url = new URL('/api/stream', window.location.origin);
        url.searchParams.append('query', query);

        eventSource = new EventSource(url);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const type = data.type || data.event_type;
                
                if (type === 'node_status' && data.node_id) {
                    updateNode(data.node_id, data.skill, data.status, data.elapsed_s, data.iteration);
                    appendLog(data.message);
                } 
                else if (type === 'start') {
                    appendLog(data.message);
                }
                else if (type === 'final') {
                    const html = marked.parse(data.final_answer || '*No output generated.*');
                    resultContent.innerHTML = html;
                    appendLog('\n--- Execution Finished ---');
                    setUIState(false);
                    eventSource.close();
                }
                else if (type === 'error') {
                    appendLog(`[ERROR] ${data.message}`, 'error');
                    executionStatus.textContent = 'Failed';
                    executionStatus.className = 'status-badge error';
                    setUIState(false);
                    eventSource.close();
                }
                else if (type === 'done') {
                    setUIState(false);
                    eventSource.close();
                }
                else {
                    appendLog(data.message);
                }
            } catch (err) {
                console.error("Error parsing SSE data", err);
            }
        };

        eventSource.onerror = (err) => {
            console.error("EventSource failed:", err);
            appendLog('[ERROR] Connection lost or server error', 'error');
            executionStatus.textContent = 'Error';
            executionStatus.className = 'status-badge error';
            setUIState(false);
            eventSource.close();
        };
    });
});
