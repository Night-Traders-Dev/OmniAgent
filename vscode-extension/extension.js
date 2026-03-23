const vscode = require('vscode');

let serverUrl = 'http://localhost:8000';

function activate(context) {
    serverUrl = vscode.workspace.getConfiguration('omniagent').get('serverUrl', 'http://localhost:8000');

    context.subscriptions.push(
        vscode.commands.registerCommand('omniagent.ask', async () => {
            const input = await vscode.window.showInputBox({ prompt: 'Ask OmniAgent anything', placeHolder: 'What do you want to do?' });
            if (!input) return;
            const reply = await sendToAgent(input);
            showResponse(reply);
        }),

        vscode.commands.registerCommand('omniagent.explain', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) return;
            const selection = editor.document.getText(editor.selection);
            if (!selection) { vscode.window.showWarningMessage('Select some code first'); return; }
            const reply = await sendToAgent(`Explain this code:\n\`\`\`\n${selection}\n\`\`\``);
            showResponse(reply);
        }),

        vscode.commands.registerCommand('omniagent.fix', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) return;
            const selection = editor.document.getText(editor.selection);
            if (!selection) { vscode.window.showWarningMessage('Select some code first'); return; }
            const reply = await sendToAgent(`Fix this code:\n\`\`\`\n${selection}\n\`\`\``);
            showResponse(reply);
        }),

        vscode.commands.registerCommand('omniagent.review', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) return;
            const content = editor.document.getText();
            const filename = editor.document.fileName;
            const reply = await sendToAgent(`Review this file (${filename}) for bugs and improvements:\n\`\`\`\n${content.substring(0, 5000)}\n\`\`\``);
            showResponse(reply);
        })
    );

    vscode.window.showInformationMessage('OmniAgent extension activated');
}

async function sendToAgent(message) {
    try {
        const response = await fetch(`${serverUrl}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, session_id: 'vscode' }),
        });
        const data = await response.json();
        return data.reply || data.error || 'No response';
    } catch (e) {
        return `Error connecting to OmniAgent: ${e.message}`;
    }
}

function showResponse(text) {
    const panel = vscode.window.createWebviewPanel('omniagent', 'OmniAgent', vscode.ViewColumn.Beside, {});
    panel.webview.html = `<!DOCTYPE html>
    <html><head><style>
        body { font-family: var(--vscode-editor-font-family); padding: 16px; color: var(--vscode-editor-foreground); }
        pre { background: var(--vscode-editor-background); padding: 12px; border-radius: 6px; overflow-x: auto; }
        code { font-size: 13px; }
    </style></head><body>
        <div>${text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>').replace(/\n/g, '<br>')}</div>
    </body></html>`;
}

function deactivate() {}

module.exports = { activate, deactivate };
