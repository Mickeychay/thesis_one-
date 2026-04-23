const DASHBOARD_URL = process.env.H2L_DASHBOARD_URL || 'http://127.0.0.1:8000/';
const CDP_LIST_URL = process.env.CHROME_CDP_LIST_URL || 'http://127.0.0.1:9222/json/list';
const CASE_TEXT = 'เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getDebuggerUrl() {
  const response = await fetch(CDP_LIST_URL);
  if (!response.ok) throw new Error(`Chrome CDP list failed: ${response.status}`);

  let targets = await response.json();
  let page = targets.find((target) => target.type === 'page' && target.webSocketDebuggerUrl);

  if (!page) {
    const newTargetUrl = CDP_LIST_URL.replace('/json/list', `/json/new?${encodeURIComponent(DASHBOARD_URL)}`);
    const created = await fetch(newTargetUrl, { method: 'PUT' });
    if (!created.ok) throw new Error(`Chrome CDP target creation failed: ${created.status}`);
    page = await created.json();
  }

  if (!page) throw new Error('No Chrome page target with a debugger URL was found.');
  return page.webSocketDebuggerUrl;
}

class CdpClient {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.errors = [];
    this.commandTimeoutMs = 20000;
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });

    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
        return;
      }

      if (message.method === 'Runtime.exceptionThrown') {
        this.errors.push(`Runtime exception: ${message.params.exceptionDetails?.text || 'unknown'}`);
      }
      if (message.method === 'Runtime.consoleAPICalled' && ['error', 'assert'].includes(message.params.type)) {
        const args = message.params.args?.map((arg) => arg.value || arg.description).join(' ');
        this.errors.push(`Console ${message.params.type}: ${args}`);
      }
      if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
        this.errors.push(`Log error: ${message.params.entry.text}`);
      }
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`${method} timed out`));
        }
      }, this.commandTimeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timeoutId);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timeoutId);
          reject(error);
        },
      });
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });

    if (result.exceptionDetails) {
      const details = result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Runtime evaluation failed';
      throw new Error(details);
    }

    return result.result?.value;
  }

  async waitFor(expression, label, timeoutMs = 30000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (await this.evaluate(expression)) return;
      await sleep(300);
    }
    const bodyText = await this.evaluate('document.body?.innerText?.slice(0, 2500) || ""');
    throw new Error(`Timed out waiting for ${label}\nCurrent page text:\n${bodyText}`);
  }

  close() {
    if (!this.socket) return Promise.resolve();
    if (this.socket.readyState === WebSocket.CLOSED) return Promise.resolve();
    return new Promise((resolve) => {
      this.socket.addEventListener('close', resolve, { once: true });
      this.socket.close();
    });
  }
}

async function clickButton(client, text) {
  await client.evaluate(`
    (() => {
      const button = [...document.querySelectorAll('button')]
        .find((item) => item.textContent.includes(${JSON.stringify(text)}));
      if (!button) throw new Error('Button not found: ${text}');
      button.click();
      return true;
    })();
  `);
}

async function main() {
  const client = new CdpClient(await getDebuggerUrl());
  await client.connect();

  await client.send('Runtime.enable');
  await client.send('Log.enable');
  await client.send('Page.enable');
  await client.send('Network.enable');
  await client.send('Network.setCacheDisabled', { cacheDisabled: true });

  const separator = DASHBOARD_URL.includes('?') ? '&' : '?';
  await client.send('Page.navigate', { url: `${DASHBOARD_URL}${separator}smoke=${Date.now()}` });
  await client.waitFor('document.readyState === "complete"', 'page load');
  await client.waitFor('document.body.innerText.includes("Run H2L Analysis")', 'analysis button');
  await client.waitFor('document.body.innerText.toLowerCase().includes("runtime clinical panel") && document.body.innerText.toLowerCase().includes("retrieval family")', 'runtime and strategy UI');
  await client.waitFor('document.body.innerText.toLowerCase().includes("runtime ready") || document.body.innerText.toLowerCase().includes("runtime degraded")', 'runtime ready/degraded', 180000);
  await client.waitFor('document.body.innerText.includes("h2l-hybrid") && document.body.innerText.includes("enable_l2=true")', 'default h2l strategy and L2');

  await client.evaluate(`
    (() => {
      const textarea = document.querySelector('textarea');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, ${JSON.stringify(CASE_TEXT)});
      textarea.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: ${JSON.stringify(CASE_TEXT)} }));
      return true;
    })();
  `);

  await clickButton(client, 'Run H2L Analysis');
  await client.waitFor('document.body.innerText.toLowerCase().includes("live data")', 'live data badge', 140000);
  await client.waitFor('document.body.innerText.toLowerCase().includes("candidate / filter trace") && document.body.innerText.toLowerCase().includes("evidence retrieval")', 'candidate and evidence panels');
  await client.waitFor('document.body.innerText.includes("retrieved") || document.body.innerText.includes("เอกสาร")', 'retrieval content');

  await clickButton(client, 'Baseline');
  await client.waitFor('document.body.innerText.includes("Strategy mode เปลี่ยนแล้ว") && document.body.innerText.toLowerCase().includes("needs analysis")', 'baseline stale state');
  await client.waitFor('[...document.querySelectorAll("button")].some((button) => button.textContent.includes("Run H2L Analysis"))', 'baseline analyze button');
  await clickButton(client, 'Run H2L Analysis');
  await client.waitFor('document.body.innerText.includes("strategy=basic") && document.body.innerText.toLowerCase().includes("live data") && !document.body.innerText.includes("Evaluating Current Case")', 'baseline strategy applied', 140000);

  await clickButton(client, 'H2L-Enhanced');
  await client.waitFor('document.body.innerText.toLowerCase().includes("needs analysis")', 'enhanced stale state');
  await client.waitFor('[...document.querySelectorAll("button")].some((button) => button.textContent.includes("Run H2L Analysis"))', 'enhanced analyze button');
  await clickButton(client, 'Run H2L Analysis');
  await client.waitFor('document.body.innerText.includes("strategy=h2l-hybrid") && document.body.innerText.toLowerCase().includes("live data") && !document.body.innerText.includes("Evaluating Current Case")', 'enhanced strategy reapplied', 140000);

  await clickButton(client, 'Sentence Polarity');
  await client.waitFor('document.body.innerText.toLowerCase().includes("lexical breakdown") && document.body.innerText.includes("เมื่อมี Sentence Polarity")', 'polarity panels');
  await client.waitFor('document.body.innerText.includes("ผู้กระทำ") && document.body.innerText.includes("ผู้ถูกกระทำ") && document.body.innerText.includes("เด็กหญิง")', 'polarity roles and current case');

  await clickButton(client, '3D Vector Space');
  await client.waitFor('document.body.innerText.toLowerCase().includes("3d vector space") && document.body.innerText.toLowerCase().includes("show radius zones") && document.body.innerText.toLowerCase().includes("vector variables")', 'vector section');
  await client.waitFor('document.querySelectorAll("[data-vector-node]").length > 1', 'vector nodes');
  await client.evaluate(`
    (() => {
      const node = [...document.querySelectorAll('[data-vector-node]')]
        .find((item) => item.getAttribute('data-vector-node') !== 'q');
      if (!node) throw new Error('No non-query vector node found');
      node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return true;
    })();
  `);
  await client.waitFor('document.body.innerText.toLowerCase().includes("active vector detail") && document.body.innerText.toLowerCase().includes("semantic distance")', 'vector active detail');
  await client.evaluate(`
    (() => {
      const input = [...document.querySelectorAll('label')]
        .find((label) => label.textContent.includes('Show distance lines'))
        ?.querySelector('input');
      if (!input) throw new Error('Distance-line toggle not found');
      input.click();
      return !input.checked;
    })();
  `);
  await client.waitFor('[...document.querySelectorAll("label")].find((label) => label.textContent.includes("Show distance lines")).querySelector("input").checked === false', 'distance-line toggle');

  await clickButton(client, 'Runtime Flow');
  await client.waitFor('document.body.innerText.toLowerCase().includes("system pipeline") && document.body.innerText.toLowerCase().includes("candidate / filter trace") && document.body.innerText.toLowerCase().includes("evidence retrieval")', 'runtime flow panels');

  await clickButton(client, 'Research Report');
  await client.waitFor('document.body.innerText.includes("Performance Provenance") && document.body.innerText.includes("System Evaluation Status") && document.body.innerText.includes("Latest Pair Reruns")', 'research report summary');
  await client.waitFor('document.body.innerText.includes("Benchmark Provenance") && document.body.innerText.includes("Polarity Provenance") && document.body.innerText.includes("Artifact Retention")', 'provenance and retention sections');
  await client.waitFor('document.body.innerText.includes("evaluate_h2l_proper.py") && document.body.innerText.includes("statistical_analysis.py") && document.body.innerText.includes("ablation_study.py") && document.body.innerText.includes("No-mock thesis contract")', 'source function labels');
  await client.waitFor('document.body.innerText.toLowerCase().includes("map") && document.body.innerText.toLowerCase().includes("mrr") && (document.body.innerText.toLowerCase().includes("ndcg@10") || document.body.innerText.toLowerCase().includes("ndcg@5"))', 'metric guidance labels');

  const startsDark = await client.evaluate('document.documentElement.classList.contains("dark")');
  if (startsDark) {
    await client.evaluate(`document.querySelector('button[aria-label="Toggle day and night theme"]').click(); true;`);
    await client.waitFor('!document.documentElement.classList.contains("dark") && localStorage.getItem("h2l-theme") === "light"', 'light theme reset');
  }
  await client.evaluate(`document.querySelector('button[aria-label="Toggle day and night theme"]').click(); true;`);
  await client.waitFor('document.documentElement.classList.contains("dark") && localStorage.getItem("h2l-theme") === "dark"', 'dark theme toggle');

  const themeState = await client.evaluate(`({
    darkClass: document.documentElement.classList.contains('dark'),
    storedTheme: localStorage.getItem('h2l-theme'),
    bodyBackground: getComputedStyle(document.body).backgroundColor,
    textareaBackground: getComputedStyle(document.querySelector('textarea')).backgroundColor
  })`);

  if (client.errors.length) {
    throw new Error(`Browser reported errors:\n${client.errors.join('\n')}`);
  }

  console.log(JSON.stringify({
    status: 'ok',
    dashboardUrl: DASHBOARD_URL,
    checks: {
      runtimeState: true,
      realCaseAnalysis: true,
      baselineEnhancedStrategy: true,
      candidateFilterEvidence: true,
      polarityCurrentCase: true,
      vectorSpace3dControls: true,
      runtimeFlow: true,
      researchStatisticsSensitivity: true,
      darkTheme: themeState,
      browserErrors: client.errors.length,
    },
  }, null, 2));

  await client.close();
  process.exit(0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
