/**
 * Argo Trading Admin Extensions
 * Controller for BacktestRunSection including section collapse, lazy AJAX loading, and canvas viewer.
 */

window.backtestRunSectionController = function(config = {}) {
    const isObj = typeof config === 'object' && config !== null;
    const initialRunId = isObj ? (config.initialRunId || null) : config;

    return {
        isLoaded: isObj ? !!config.isLoaded : false,
        isLoading: false,
        isCollapsed: isObj ? !!config.isCollapsed : false,
        refreshUrl: isObj ? (config.refreshUrl || '') : '',
        selectedRunId: initialRunId || null,
        activeTab: 'log',
        canvasTitle: initialRunId ? `Run #${initialRunId} - LOG` : '',
        canvasContent: '',
        canvasHtml: '',
        canvasUrl: '',
        canvasLoading: false,
        copied: false,
        expanded: false,

        init() {
            if (this.selectedRunId) {
                this.loadContent(this.selectedRunId, 'log');
            }
        },

        loadSection() {
            if (this.isLoaded || this.isLoading) return;
            this.isLoading = true;
            this._showSectionLoading();
            
            const url = this._resolveUrl(this.refreshUrl);
            fetch(url)
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(data => this._handleSectionLoaded(data))
                .catch(err => this._handleSectionError(err))
                .finally(() => {
                    this.isLoading = false;
                });
        },

        _resolveUrl(url) {
            if (!url) return '';
            if (url.startsWith('/') || url.startsWith('http')) return url;
            const baseUrl = typeof getAdminBaseUrl === 'function' ? getAdminBaseUrl() : window.location.pathname.replace(/\/\d+\/change\/?$/, '');
            return `${baseUrl.replace(/\/$/, '')}/${url}`;
        },

        _showSectionLoading() {
            if (this.$refs && this.$refs.content) {
                this.$refs.content.innerHTML = '<div class="flex flex-col items-center justify-center p-8 text-center w-full gap-2"><span class="material-symbols-outlined animate-spin text-3xl text-primary-600 dark:text-primary-400">progress_activity</span><span class="text-xs text-gray-500 font-medium animate-pulse">Loading backtest runs...</span></div>';
            }
        },

        _handleSectionLoaded(data) {
            if (this.$refs && this.$refs.content) {
                if (window.setHTMLWithScripts) {
                    window.setHTMLWithScripts(this.$refs.content, data.html);
                } else {
                    this.$refs.content.innerHTML = data.html;
                }
            }
            this.isLoaded = true;
            this.$nextTick(() => {
                const root = (this.$refs && this.$refs.content) || document;
                const firstRow = root.querySelector('[data-run-id]');
                if (firstRow && firstRow.dataset.runId) {
                    this.selectRun(parseInt(firstRow.dataset.runId, 10), this.activeTab || 'log');
                }
            });
        },

        _handleSectionError(err) {
            if (this.$refs && this.$refs.content) {
                this.$refs.content.innerHTML = '<div class="p-4 text-xs text-red-500">Failed to load runs: ' + err.message + '</div>';
            }
        },

        selectRun(runId, tab = null) {
            this.selectedRunId = runId;
            const targetTab = tab || this.activeTab || 'log';
            this.loadContent(runId, targetTab);
        },

        switchTab(tab) {
            this.activeTab = tab;
            if (this.selectedRunId) {
                this.loadContent(this.selectedRunId, tab);
            }
        },

        loadContent(runId, tab) {
            this.selectedRunId = runId;
            this.activeTab = tab;
            const baseUrl = typeof getAdminBaseUrl === 'function' ? getAdminBaseUrl() : window.location.pathname.replace(/\/\d+\/change\/?$/, '');
            const targetUrl = `${baseUrl.replace(/\/$/, '')}/run-content/${runId}/${tab}/`;
            this.canvasUrl = targetUrl;
            this.canvasTitle = `Run #${runId} - ${tab.toUpperCase()}`;
            this.copied = false;
            this.canvasLoading = true;

            fetch(`${targetUrl}?format=json`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(data => this._renderContent(data, tab))
            .catch(err => this._renderError(err, tab))
            .finally(() => {
                this.canvasLoading = false;
            });
        },

        _renderContent(data, tab) {
            this.canvasTitle = data.title || this.canvasTitle;
            if (tab === 'html') {
                const rawHtml = data.html || '<div class="p-6 text-center text-xs text-gray-400">No tearsheet HTML recorded for this run.</div>';
                this.canvasHtml = rawHtml;
                this.canvasContent = rawHtml;
                this.$nextTick(() => this.injectHtml(rawHtml));
            } else {
                this.canvasContent = data.content || 'No content recorded.';
            }
        },

        _renderError(err, tab) {
            const errMsg = 'Error loading content: ' + err;
            this.canvasContent = errMsg;
            if (tab === 'html') {
                this.$nextTick(() => this.injectHtml(`<div class="p-4 text-xs text-red-500 font-sans">${errMsg}</div>`));
            }
        },

        injectHtml(html) {
            const container = (this.$refs && this.$refs.htmlContainer) || (this.$refs && this.$refs.content && this.$refs.content.querySelector('[data-canvas-html]')) || document.querySelector('[data-canvas-html]');
            if (!container) return;

            let cleanHtml = html;
            const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
            const styleMatches = html.match(/<style[^>]*>[\s\S]*?<\/style>/gi) || [];
            if (bodyMatch && bodyMatch[1]) {
                cleanHtml = styleMatches.join('\n') + bodyMatch[1];
            }

            if (window.setHTMLWithScripts) {
                window.setHTMLWithScripts(container, cleanHtml);
            } else {
                container.innerHTML = cleanHtml;
                const scripts = container.querySelectorAll('script');
                scripts.forEach(s => {
                    const newScript = document.createElement('script');
                    Array.from(s.attributes).forEach(a => newScript.setAttribute(a.name, a.value));
                    newScript.textContent = s.textContent;
                    s.parentNode.replaceChild(newScript, s);
                });
            }
        },

        copyContent() {
            const textToCopy = this.activeTab === 'html' ? (this.canvasHtml || '') : (this.canvasContent || '');
            if (textToCopy) {
                navigator.clipboard.writeText(textToCopy);
                this.copied = true;
                setTimeout(() => { this.copied = false; }, 2000);
            }
        }
    };
};

window.backtestRunViewer = window.backtestRunSectionController;
