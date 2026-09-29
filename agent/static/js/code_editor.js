// Standalone Modern Python Code Editor for Django Unfold
// Provides syntax highlighting, auto-indentation, line numbers, and seamless AJAX form integration.

(function() {
    "use strict";

    function escapeHtml(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    const PY_PATTERN = /("""[\s\S]*?"""|'''[\s\S]*?''')|(#[^\n]*)|((?:[rubfRUBF]{1,2})?(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))|(@[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)|(\bdef\s+)([a-zA-Z_]\w*)|(\bclass\s+)([a-zA-Z_]\w*)|(\b(?:and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b)|(\b(?:True|False|None)\b)|(\b(?:self|cls)\b)|(\b(?:abs|all|any|bin|bool|bytearray|bytes|callable|chr|classmethod|compile|complex|delattr|dict|dir|divmod|enumerate|eval|exec|filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|isinstance|issubclass|iter|len|list|locals|map|max|memoryview|min|next|object|oct|open|ord|pow|print|property|range|repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|vars|zip)\b)|(\b0x[0-9a-fA-F]+\b|\b0b[01]+\b|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?j?\b)|([+\-*\/%&|^~<>!=:]+)/g;

    function highlightPython(code) {
        let lastIndex = 0;
        let html = "";
        PY_PATTERN.lastIndex = 0;
        let match;

        while ((match = PY_PATTERN.exec(code)) !== null) {
            if (match.index > lastIndex) {
                html += escapeHtml(code.slice(lastIndex, match.index));
            }

            const [
                full,
                docstr,
                comm,
                str,
                dec,
                defKw,
                defName,
                clsKw,
                clsName,
                kw,
                atom,
                selfVar,
                builtin,
                num,
                op
            ] = match;

            if (docstr) {
                html += `<span class="tok-docstr">${escapeHtml(docstr)}</span>`;
            } else if (comm) {
                html += `<span class="tok-comm">${escapeHtml(comm)}</span>`;
            } else if (str) {
                html += `<span class="tok-str">${escapeHtml(str)}</span>`;
            } else if (dec) {
                html += `<span class="tok-dec">${escapeHtml(dec)}</span>`;
            } else if (defKw && defName) {
                html += `<span class="tok-kw">${escapeHtml(defKw)}</span><span class="tok-def">${escapeHtml(defName)}</span>`;
            } else if (clsKw && clsName) {
                html += `<span class="tok-kw">${escapeHtml(clsKw)}</span><span class="tok-class">${escapeHtml(clsName)}</span>`;
            } else if (kw) {
                html += `<span class="tok-kw">${escapeHtml(kw)}</span>`;
            } else if (atom) {
                html += `<span class="tok-atom">${escapeHtml(atom)}</span>`;
            } else if (selfVar) {
                html += `<span class="tok-self">${escapeHtml(selfVar)}</span>`;
            } else if (builtin) {
                html += `<span class="tok-builtin">${escapeHtml(builtin)}</span>`;
            } else if (num) {
                html += `<span class="tok-num">${escapeHtml(num)}</span>`;
            } else if (op) {
                html += `<span class="tok-op">${escapeHtml(op)}</span>`;
            } else {
                html += escapeHtml(full);
            }

            lastIndex = PY_PATTERN.lastIndex;
        }

        if (lastIndex < code.length) {
            html += escapeHtml(code.slice(lastIndex));
        }

        // Trailing newline visual alignment
        if (code.endsWith("\n") || code.length === 0) {
            html += "\n ";
        }

        return html;
    }

    function createEditor(originalTextarea) {
        if (originalTextarea.codeEditorWrapper) {
            return originalTextarea.codeEditor;
        }

        const language = originalTextarea.dataset.language || "python";

        // Build wrapper DOM structure
        const wrapper = document.createElement("div");
        wrapper.className = "code-editor-wrapper";

        const toolbar = document.createElement("div");
        toolbar.className = "code-editor-toolbar";
        toolbar.innerHTML = `
            <div class="flex items-center gap-2">
                <span class="code-editor-badge">${language}</span>
            </div>
            <div class="code-editor-info">
                <span class="code-editor-cursor-pos">Ln 1, Col 1</span>
                <span class="code-editor-line-count">1 line</span>
            </div>
        `;

        const body = document.createElement("div");
        body.className = "code-editor-body";

        const gutter = document.createElement("div");
        gutter.className = "code-editor-gutter";

        const area = document.createElement("div");
        area.className = "code-editor-area";

        const highlightPre = document.createElement("pre");
        highlightPre.className = "code-editor-highlight";
        const highlightCode = document.createElement("code");
        highlightPre.appendChild(highlightCode);

        // Place elements in wrapper
        area.appendChild(highlightPre);
        body.appendChild(gutter);
        body.appendChild(area);
        wrapper.appendChild(toolbar);
        wrapper.appendChild(body);

        // Insert wrapper directly before original textarea and move textarea inside area
        originalTextarea.parentNode.insertBefore(wrapper, originalTextarea);
        area.appendChild(originalTextarea);

        originalTextarea.classList.add("code-editor-textarea");
        originalTextarea.setAttribute("spellcheck", "false");
        originalTextarea.setAttribute("autocomplete", "off");
        originalTextarea.setAttribute("autocapitalize", "off");

        const cursorPosEl = toolbar.querySelector(".code-editor-cursor-pos");
        const lineCountEl = toolbar.querySelector(".code-editor-line-count");

        let lastLineCount = 0;

        function updateGutter(lineCount, currentLine) {
            if (lineCount !== lastLineCount) {
                let gutterHtml = "";
                for (let i = 1; i <= lineCount; i++) {
                    const activeClass = i === currentLine ? " active" : "";
                    gutterHtml += `<div class="code-editor-line-num${activeClass}" data-line="${i}">${i}</div>`;
                }
                gutter.innerHTML = gutterHtml;
                lastLineCount = lineCount;
            } else {
                const prevActive = gutter.querySelector(".code-editor-line-num.active");
                if (prevActive) prevActive.classList.remove("active");
                const currentEl = gutter.querySelector(`.code-editor-line-num[data-line="${currentLine}"]`);
                if (currentEl) currentEl.classList.add("active");
            }
        }

        function updateCursorInfo() {
            const val = originalTextarea.value;
            const pos = originalTextarea.selectionStart;
            const linesBefore = val.substring(0, pos).split("\n");
            const currentLine = linesBefore.length;
            const currentCol = linesBefore[linesBefore.length - 1].length + 1;
            const totalLines = val.split("\n").length;

            cursorPosEl.textContent = `Ln ${currentLine}, Col ${currentCol}`;
            lineCountEl.textContent = `${totalLines} line${totalLines === 1 ? "" : "s"}`;
            updateGutter(totalLines, currentLine);
        }

        function renderHighlight() {
            highlightCode.innerHTML = highlightPython(originalTextarea.value);
            syncScroll();
        }

        function syncScroll() {
            highlightPre.scrollTop = originalTextarea.scrollTop;
            highlightPre.scrollLeft = originalTextarea.scrollLeft;
            gutter.scrollTop = originalTextarea.scrollTop;
        }

        function handleInput() {
            renderHighlight();
            updateCursorInfo();
        }

        // Synchronize scroll events
        originalTextarea.addEventListener("scroll", syncScroll, { passive: true });
        originalTextarea.addEventListener("input", handleInput);
        originalTextarea.addEventListener("keyup", updateCursorInfo);
        originalTextarea.addEventListener("click", updateCursorInfo);
        originalTextarea.addEventListener("select", updateCursorInfo);

        // Smart indentation and keyboard handling
        originalTextarea.addEventListener("keydown", function(e) {
            const val = originalTextarea.value;
            const start = originalTextarea.selectionStart;
            const end = originalTextarea.selectionEnd;

            // Tab / Shift-Tab
            if (e.key === "Tab") {
                e.preventDefault();
                if (e.shiftKey) {
                    // Unindent line(s)
                    const lineStart = val.lastIndexOf("\n", start - 1) + 1;
                    const lineEnd = val.indexOf("\n", end);
                    const actualEnd = lineEnd === -1 ? val.length : lineEnd;
                    const lines = val.substring(lineStart, actualEnd).split("\n");
                    const unindented = lines.map(line => line.startsWith("    ") ? line.slice(4) : line.replace(/^\s{1,3}/, "")).join("\n");
                    originalTextarea.setRangeText(unindented, lineStart, actualEnd, "select");
                } else if (start !== end) {
                    // Indent selected lines
                    const lineStart = val.lastIndexOf("\n", start - 1) + 1;
                    const lineEnd = val.indexOf("\n", end);
                    const actualEnd = lineEnd === -1 ? val.length : lineEnd;
                    const lines = val.substring(lineStart, actualEnd).split("\n");
                    const indented = lines.map(line => "    " + line).join("\n");
                    originalTextarea.setRangeText(indented, lineStart, actualEnd, "select");
                } else {
                    // Insert 4 spaces
                    originalTextarea.setRangeText("    ", start, end, "end");
                }
                handleInput();
                return;
            }

            // Enter key: Maintain indent + auto-indent after colon
            if (e.key === "Enter") {
                e.preventDefault();
                const before = val.substring(0, start);
                const currentLine = before.split("\n").pop() || "";
                const indentMatch = currentLine.match(/^(\s*)/);
                let indentStr = indentMatch ? indentMatch[1] : "";
                if (currentLine.trim().endsWith(":")) {
                    indentStr += "    ";
                }
                originalTextarea.setRangeText("\n" + indentStr, start, end, "end");
                handleInput();
                return;
            }

            // Backspace on 4-space boundary
            if (e.key === "Backspace" && start === end) {
                const before = val.substring(0, start);
                const currentLine = before.split("\n").pop() || "";
                if (currentLine.length > 0 && currentLine.length % 4 === 0 && /^ +$/.test(currentLine)) {
                    e.preventDefault();
                    originalTextarea.setRangeText("", start - 4, start, "end");
                    handleInput();
                    return;
                }
            }

            // Auto-closing quotes and brackets
            const pairs = { "(": ")", "[": "]", "{": "}", "\"": "\"", "'": "'" };
            if (pairs[e.key] && start === end) {
                const nextChar = val[start];
                if ((e.key === "\"" || e.key === "'") && nextChar === e.key) {
                    e.preventDefault();
                    originalTextarea.setSelectionRange(start + 1, start + 1);
                    return;
                }
                e.preventDefault();
                const closeChar = pairs[e.key];
                originalTextarea.setRangeText(e.key + closeChar, start, end, "end");
                originalTextarea.setSelectionRange(start + 1, start + 1);
                handleInput();
                return;
            }
        });

        // Editor controller interface
        const controller = {
            save: () => {
                return originalTextarea.value;
            },
            getValue: () => {
                return originalTextarea.value;
            },
            setValue: (newVal) => {
                originalTextarea.value = newVal;
                handleInput();
            },
            refresh: () => {
                renderHighlight();
                updateCursorInfo();
            },
            focus: () => {
                originalTextarea.focus();
            }
        };

        originalTextarea.codeEditor = controller;
        originalTextarea.codeEditorWrapper = wrapper;

        // Shim for compatibility with generic AJAX callers
        originalTextarea.easymde = {
            save: () => controller.save(),
            value: () => controller.getValue(),
            codemirror: controller
        };

        // Initial render
        handleInput();

        // Handle accordion expansion and visibility changes
        if (window.IntersectionObserver) {
            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        controller.refresh();
                    }
                });
            }, { threshold: 0.05 });
            observer.observe(wrapper);
        }

        setTimeout(() => controller.refresh(), 50);
        setTimeout(() => controller.refresh(), 250);

        return controller;
    }

    window.initializeCodeEditors = function(container = document) {
        const textareas = container.querySelectorAll('textarea[data-code-editor="true"], textarea.code-editor-textarea');
        textareas.forEach(textarea => {
            if (textarea.codeEditor) {
                textarea.codeEditor.refresh();
            } else {
                createEditor(textarea);
            }
        });
    };

    // Auto-initialize on DOM ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            window.initializeCodeEditors(document);
        });
    } else {
        window.initializeCodeEditors(document);
    }
})();
