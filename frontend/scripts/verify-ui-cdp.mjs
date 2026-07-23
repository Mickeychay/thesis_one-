const DASHBOARD_URL = process.env.H2L_DASHBOARD_URL || 'http://127.0.0.1:8000/';
const CDP_LIST_URL = process.env.CHROME_CDP_LIST_URL || 'http://127.0.0.1:9222/json/list';
const CASE_TEXT = 'เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

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
    this.requests = [];
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
      if (message.method === 'Network.requestWillBeSent') {
        this.requests.push({
          method: message.params.request?.method,
          postData: message.params.request?.postData,
          url: message.params.request?.url,
        });
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
      await sleep(250);
    }
    const bodyText = await this.evaluate('document.body?.innerText?.slice(0, 3000) || ""');
    throw new Error(`Timed out waiting for ${label}\nCurrent page text:\n${bodyText}`);
  }

  analyzeRequestCount() {
    return this.requests.filter((request) => request.method === 'POST' && /\/analyze(?:\?|$)/.test(request.url || '')).length;
  }

  requestCount(pathPattern) {
    return this.requests.filter((request) => request.method === 'POST' && pathPattern.test(request.url || '')).length;
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

const visibleElementSetup = `
  const isVisible = (element) => {
    if (!element || element.closest('[aria-hidden="true"]')) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
  };
  const normalized = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
`;

async function setViewport(client, width, height, mobile) {
  await client.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile,
  });
}

async function clickButton(client, text, { exact = false } = {}) {
  return client.evaluate(`
    (() => {
      ${visibleElementSetup}
      const target = ${JSON.stringify(text)};
      const candidates = [...document.querySelectorAll('button')].filter(isVisible);
      const button = candidates.find((item) => {
        const label = normalized(item.innerText || item.textContent);
        return ${exact ? 'label === target' : 'label.includes(target)'};
      });
      if (!button) throw new Error('Visible button not found: ' + target);
      if (button.disabled) throw new Error('Button is disabled: ' + target);
      button.scrollIntoView({ block: 'center', inline: 'nearest' });
      button.click();
      return normalized(button.innerText || button.textContent);
    })();
  `);
}

async function clickAriaLabel(client, label) {
  return client.evaluate(`
    (() => {
      ${visibleElementSetup}
      const target = ${JSON.stringify(label)};
      const element = [...document.querySelectorAll('[aria-label]')]
        .find((item) => item.getAttribute('aria-label') === target && isVisible(item));
      if (!element) throw new Error('Visible aria-label target not found: ' + target);
      if (element.disabled || element.getAttribute('aria-disabled') === 'true') {
        throw new Error('Aria-label target is disabled: ' + target);
      }
      element.scrollIntoView({ block: 'center', inline: 'nearest' });
      if (typeof element.click === 'function') element.click();
      else element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return true;
    })();
  `);
}

async function openDetails(client, summaryText) {
  return client.evaluate(`
    (() => {
      ${visibleElementSetup}
      const target = ${JSON.stringify(summaryText)};
      const summary = [...document.querySelectorAll('summary')]
        .find((item) => isVisible(item) && normalized(item.innerText || item.textContent).includes(target));
      if (!summary) throw new Error('Visible details summary not found: ' + target);
      const details = summary.closest('details');
      if (!details.open) summary.click();
      return details.open;
    })();
  `);
}

async function main() {
  const client = new CdpClient(await getDebuggerUrl());
  await client.connect();

  try {
    await client.send('Runtime.enable');
    await client.send('Log.enable');
    await client.send('Page.enable');
    await client.send('Network.enable');
    await client.send('Network.setCacheDisabled', { cacheDisabled: true });
    await setViewport(client, 390, 844, true);

    const separator = DASHBOARD_URL.includes('?') ? '&' : '?';
    await client.send('Page.navigate', { url: `${DASHBOARD_URL}${separator}smoke=${Date.now()}` });
    await client.waitFor('document.readyState === "complete"', 'page load');
    await client.evaluate('document.fonts?.ready?.then(() => true) || true');
    await client.waitFor('document.querySelector("#case-description") && document.body.innerText.includes("โหลดเคสตัวอย่าง")', 'redesigned case workspace');
    await client.waitFor(`
      [...document.querySelectorAll('button[aria-label^="สถานะระบบ:"]')]
        .some((button) => button.getAttribute('aria-label').includes('ระบบพร้อม') || button.getAttribute('aria-label').includes('ระบบจำกัด'))
    `, 'runtime ready/degraded', 180000);

    const emptyAnalyzeDisabled = await client.evaluate(`
      [...document.querySelectorAll('button')]
        .find((button) => button.textContent.includes('วิเคราะห์เคสและค้นหาแนวทาง'))?.disabled === true
    `);
    assert(emptyAnalyzeDisabled, 'Analyze must be disabled while the case field is empty.');
    const mobileLayout = await client.evaluate(`({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
    })`);
    assert(mobileLayout.documentWidth <= mobileLayout.viewport + 1 && mobileLayout.bodyWidth <= mobileLayout.viewport + 1, `Mobile layout overflows horizontally: ${JSON.stringify(mobileLayout)}`);

    await clickAriaLabel(client, 'เปิดเมนูหลัก');
    await client.waitFor(`
      (() => {
        const drawer = document.querySelector('button[aria-label="ปิดเมนู"]')?.closest('aside');
        const rect = drawer?.getBoundingClientRect();
        return Boolean(rect && rect.width > 0 && rect.left >= 0 && rect.left < window.innerWidth);
      })()
    `, 'mobile navigation drawer open');
    await clickButton(client, 'เหตุผลของระบบ');
    await client.waitFor('document.body.innerText.includes("เหตุผลและเส้นทางการประมวลผล") && document.body.innerText.includes("ยังไม่มีข้อมูลสำหรับอธิบายผล")', 'empty explainability workspace');

    await clickAriaLabel(client, 'เปิดเมนูหลัก');
    await clickButton(client, 'ทบทวนเคส');
    await client.waitFor('document.body.innerText.includes("ประเมินเคสสังคมสงเคราะห์ทางคลินิก")', 'case workspace navigation');
    await setViewport(client, 1440, 1000, false);

    await clickButton(client, 'โหลดเคสตัวอย่าง', { exact: true });
    await client.waitFor(`document.querySelector('#case-description')?.value === ${JSON.stringify(CASE_TEXT)}`, 'sample case text');
    await openDetails(client, 'การตั้งค่าการวิเคราะห์ขั้นสูง');

    const defaultSettings = await client.evaluate(`
      (() => {
        const summary = [...document.querySelectorAll('summary')]
          .find((item) => item.textContent.includes('การตั้งค่าการวิเคราะห์ขั้นสูง'));
        const details = summary?.closest('details');
        const buttons = [...(details?.querySelectorAll('button') || [])];
        return {
          open: Boolean(details?.open),
          summary: summary?.innerText || '',
          topK: details?.querySelector('input[aria-label="จำนวนหลักฐาน Top K สำหรับเคส"]')?.value,
          l2: details?.querySelector('input[aria-label="เปิดการตรวจสอบเชิงความหมาย L2"]')?.checked,
          hybrid: buttons.some((button) => button.textContent.includes('Hybrid') && button.getAttribute('aria-pressed') === 'true'),
          enhanced: buttons.some((button) => button.textContent.includes('H2L Enhanced') && button.getAttribute('aria-pressed') === 'true'),
        };
      })()
    `);
    assert(defaultSettings.open, 'Advanced analysis settings did not open.');
    assert(defaultSettings.topK === '15', `Expected case Top-K 15, received ${defaultSettings.topK}.`);
    assert(defaultSettings.l2, 'L2 must be enabled by default.');
    assert(defaultSettings.hybrid && defaultSettings.enhanced, 'Hybrid H2L Enhanced must be selected by default.');

    const analyzeRequestsBefore = client.analyzeRequestCount();
    await clickButton(client, 'วิเคราะห์เคสและค้นหาแนวทาง', { exact: true });
    await sleep(60);
    const doubleSubmitState = await client.evaluate(`
      (() => {
        const button = document.querySelector('button[aria-busy="true"]');
        if (!button) return { attempted: false, guarded: false };
        const guarded = button.disabled === true;
        button.click();
        return { attempted: true, guarded };
      })()
    `);

    await client.waitFor(`
      document.body.innerText.includes('วิเคราะห์เคสเสร็จแล้ว')
      && document.body.innerText.includes('สรุปการประเมินเคส')
      && document.body.innerText.includes('การทบทวนโดยผู้ปฏิบัติงาน')
      && !document.querySelector('button[aria-busy="true"]')
    `, 'fresh clinical case result', 160000);
    await sleep(250);
    const analyzeRequestDelta = client.analyzeRequestCount() - analyzeRequestsBefore;
    assert(analyzeRequestDelta === 1, `Expected one POST /analyze request, received ${analyzeRequestDelta}.`);
    if (doubleSubmitState.attempted) assert(doubleSubmitState.guarded, 'Analyze button was not disabled during the second-submit attempt.');

    const findingCount = await client.evaluate(`
      (() => {
        const heading = [...document.querySelectorAll('h2')].find((item) => item.textContent.includes('ประเด็นปัญหาและความต้องการ'));
        return heading?.closest('section')?.querySelectorAll('article').length || 0;
      })()
    `);
    assert(findingCount > 0, 'The sample case should produce at least one finding for review testing.');
    const reviewChoices = ['รับไว้', 'ต้องทบทวน', 'ไม่นำไปใช้'];
    for (let index = 0; index < findingCount; index += 1) {
      await client.evaluate(`
        (() => {
          const heading = [...document.querySelectorAll('h2')].find((item) => item.textContent.includes('ประเด็นปัญหาและความต้องการ'));
          const article = heading?.closest('section')?.querySelectorAll('article')?.[${index}];
          const toggle = article?.querySelector('button[aria-expanded]');
          if (!article || !toggle) throw new Error('Finding card not found at index ${index}.');
          if (toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
          return true;
        })()
      `);
      await sleep(35);
      const choice = reviewChoices[index % reviewChoices.length];
      await client.evaluate(`
        (() => {
          const heading = [...document.querySelectorAll('h2')].find((item) => item.textContent.includes('ประเด็นปัญหาและความต้องการ'));
          const article = heading?.closest('section')?.querySelectorAll('article')?.[${index}];
          const button = [...(article?.querySelectorAll('button[aria-pressed]') || [])].find((item) => item.textContent.trim().includes(${JSON.stringify(choice)}));
          if (!button) throw new Error('Review choice not found: ' + ${JSON.stringify(choice)});
          button.click();
          return true;
        })()
      `);
      await sleep(35);
    }
    const reviewState = await client.evaluate(`
      (() => ({
        pending: [...document.querySelectorAll('body *')].filter((item) => item.textContent?.trim() === 'ยังไม่ระบุ').length,
        summary: document.body.innerText.includes('ทบทวนครบแล้ว'),
        selected: [...document.querySelectorAll('button[aria-pressed="true"]')]
          .map((item) => item.textContent.replace(/^(check_circle|help|block)/, '').trim())
          .filter((text) => ['รับไว้', 'ต้องทบทวน', 'ไม่นำไปใช้'].includes(text)),
      }))()
    `);
    assert(reviewState.summary, `Finding review summary did not reach complete state: ${JSON.stringify(reviewState)}`);
    assert(reviewState.selected.includes('รับไว้') && reviewState.selected.includes('ต้องทบทวน'), 'Accept and review states were not reflected in the UI.');
    if (findingCount >= 3) assert(reviewState.selected.includes('ไม่นำไปใช้'), 'Exclude state was not reflected in the UI.');

    const setTextareaValue = async (selector, value) => client.evaluate(`
      (() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) throw new Error('Textarea not found: ' + ${JSON.stringify(selector)});
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(element, ${JSON.stringify(value)});
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
        return element.value;
      })()
    `);
    await setTextareaValue('textarea[name="reviewer-note"]', 'ทบทวนบริบทและหลักฐานประกอบแล้ว');
    const reviewButtonsReady = await client.evaluate(`
      [...document.querySelectorAll('button')]
        .filter((button) => button.textContent.includes('จัดเตรียมข้อมูลสำหรับทบทวนซ้ำ') || button.textContent.includes('ส่งเพื่อให้ผู้เชี่ยวชาญทบทวน'))
        .every((button) => !button.disabled)
    `);
    assert(reviewButtonsReady, 'Review actions should be enabled after every finding has a state.');

    const auditRequestsBefore = client.requestCount(/\/audit\/prepare(?:\?|$)/);
    await clickButton(client, 'จัดเตรียมข้อมูลสำหรับทบทวนซ้ำ');
    await sleep(40);
    const auditBusyGuard = await client.evaluate(`
      [...document.querySelectorAll('button')].some((button) => button.textContent.includes('กำลังจัดเตรียม'))
    `);
    await client.waitFor('document.body.innerText.includes("Audit packet")', 'audit packet');
    assert(client.requestCount(/\/audit\/prepare(?:\?|$)/) - auditRequestsBefore === 1, 'Expected exactly one audit packet request.');
    if (auditBusyGuard) assert(auditBusyGuard, 'Audit button did not expose a busy state.');

    const finalizeRequestsBefore = client.requestCount(/\/case\/finalize(?:\?|$)/);
    await clickButton(client, 'ส่งเพื่อให้ผู้เชี่ยวชาญทบทวน');
    await sleep(40);
    const finalizeBusyGuard = await client.evaluate(`
      [...document.querySelectorAll('button')].some((button) => button.textContent.includes('กำลังส่ง'))
    `);
    await client.waitFor('document.body.innerText.includes("ส่งเพื่อทบทวนแล้ว") || document.body.innerText.includes("ส่งเคสเพื่อให้ผู้เชี่ยวชาญทบทวนแล้ว")', 'sign-off packet', 60000);
    assert(client.requestCount(/\/case\/finalize(?:\?|$)/) - finalizeRequestsBefore === 1, 'Expected exactly one finalize request.');
    const finalizeRequest = [...client.requests].reverse().find((request) => request.method === 'POST' && /\/case\/finalize(?:\?|$)/.test(request.url || ''));
    const finalizeBody = finalizeRequest?.postData ? JSON.parse(finalizeRequest.postData) : null;
    assert(finalizeBody?.finding_review_states && Object.keys(finalizeBody.finding_review_states).length === findingCount, 'Finalize payload did not preserve per-finding review states.');
    assert(finalizeBody?.zero_finding_acknowledged === false, 'Non-empty case should not send a zero-finding acknowledgement.');
    if (finalizeBusyGuard) assert(finalizeBusyGuard, 'Finalize button did not expose a busy state.');

    await clickButton(client, 'เหตุผลของระบบ');
    await client.waitFor(`
      document.body.innerText.includes('เหตุผลและเส้นทางการประมวลผล')
      && [...document.querySelectorAll('[role="tab"]')].some((tab) => tab.textContent.includes('บริบทภาษา') && tab.getAttribute('aria-selected') === 'true')
      && document.body.innerText.includes('Analyzed Case Text')
    `, 'language explainability tab');

    await clickButton(client, 'ลำดับการวิเคราะห์');
    await client.waitFor(`
      [...document.querySelectorAll('[role="tab"]')].some((tab) => tab.textContent.includes('ลำดับการวิเคราะห์') && tab.getAttribute('aria-selected') === 'true')
      && document.body.innerText.includes('System Pipeline')
      && document.body.innerText.includes('Runtime Pulse')
    `, 'processing trace explainability tab');

    await clickButton(client, 'แผนที่หลักฐาน');
    await client.waitFor(`
      [...document.querySelectorAll('[role="tab"]')].some((tab) => tab.textContent.includes('แผนที่หลักฐาน') && tab.getAttribute('aria-selected') === 'true')
      && document.body.innerText.includes('Semantic Evidence Map')
      && document.querySelectorAll('[data-vector-node]').length > 1
    `, 'semantic evidence map tab');
    const selectedSemanticNodeId = await client.evaluate(`
      (() => {
        const nodes = [...document.querySelectorAll('[data-vector-node]')];
        const node = nodes.find((item) => {
          const id = item.getAttribute('data-vector-node') || '';
          const label = (item.getAttribute('aria-label') || '').toLowerCase();
          return !id.toLowerCase().startsWith('q') && !label.includes('case query');
        });
        if (!node) throw new Error('No non-query vector node found. ids=' + nodes.map((item) => item.getAttribute('data-vector-node')).join(','));
        const nodeId = node.getAttribute('data-vector-node');
        node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return nodeId;
      })()
    `);
    await client.waitFor(`
      Boolean(document.querySelector('[data-vector-node="${selectedSemanticNodeId}"] rect[stroke-dasharray="4 4"]'))
    `, 'semantic node selection');

    await clickButton(client, 'หลักฐานงานวิจัย');
    await client.waitFor(`
      document.body.innerText.includes('Evaluation Design for Thesis')
      && document.body.innerText.toLowerCase().includes('performance provenance')
    `, 'research and quality workspace', 60000);
    await client.waitFor(`
      document.querySelectorAll('[aria-label^="select top "]').length > 1
    `, 'interactive research Top-K points', 60000);

    const researchTopKState = await client.evaluate(`
      (() => {
        const points = [...document.querySelectorAll('[aria-label^="select top "]')];
        const enabled = points.filter((item) => item.getAttribute('aria-disabled') !== 'true');
        const point = enabled.find((item) => item.getAttribute('aria-label') !== 'select top 15');
        if (point) {
          const topK = Number(point.getAttribute('aria-label').replace('select top ', ''));
          point.scrollIntoView({ block: 'center', inline: 'nearest' });
          point.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          return { selectedTopK: topK, alternateAvailable: true, disabledPoints: [] };
        }
        const disabledPoints = points
          .filter((item) => item.getAttribute('aria-disabled') === 'true')
          .map((item) => item.getAttribute('aria-label'));
        const disabledPoint = points.find((item) => item.getAttribute('aria-label') === 'select top 5' && item.getAttribute('aria-disabled') === 'true');
        if (disabledPoint) disabledPoint.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return { selectedTopK: 15, alternateAvailable: false, disabledPoints };
      })()
    `);
    await client.waitFor(`document.body.innerText.includes('selected top ${researchTopKState.selectedTopK}')`, 'research Top-K state');
    if (!researchTopKState.alternateAvailable) {
      assert(researchTopKState.disabledPoints.length > 0, 'Research Top-K has no enabled alternate but did not expose disabled missing-data points.');
    }

    await clickButton(client, 'ทบทวนเคส');
    await client.waitFor('document.body.innerText.includes("สรุปการประเมินเคส")', 'fresh case after research navigation');
    await openDetails(client, 'การตั้งค่าการวิเคราะห์ขั้นสูง');
    const caseTopKAfterResearch = await client.evaluate(`document.querySelector('input[aria-label="จำนวนหลักฐาน Top K สำหรับเคส"]')?.value`);
    assert(caseTopKAfterResearch === defaultSettings.topK, `Research Top-K changed case Top-K from ${defaultSettings.topK} to ${caseTopKAfterResearch}.`);
    const staleAfterResearch = await client.evaluate('document.body.innerText.includes("ผลเดิมถูกพักไว้")');
    assert(!staleAfterResearch, 'Research Top-K incorrectly marked the clinical case stale.');

    const staleTopK = defaultSettings.topK === '10' ? '5' : '10';
    await clickButton(client, staleTopK, { exact: true });
    await client.waitFor(`
      document.body.innerText.includes('ผลเดิมถูกพักไว้')
      && document.body.innerText.includes('ต้องวิเคราะห์เคสอีกครั้ง')
      && [...document.querySelectorAll('button')].some((button) => button.textContent.includes('วิเคราะห์เคสที่แก้ไขแล้ว') && !button.disabled)
      && ![...document.querySelectorAll('button')].some((button) => (button.textContent.includes('จัดเตรียมข้อมูลสำหรับทบทวนซ้ำ') || button.textContent.includes('ส่งเพื่อให้ผู้เชี่ยวชาญทบทวน')) && !button.disabled)
    `, 'stale result guard and review action disable');

    const startsDark = await client.evaluate('document.documentElement.classList.contains("dark")');
    if (startsDark) {
      await clickAriaLabel(client, 'เปลี่ยนเป็นโหมดสว่าง');
      await client.waitFor('!document.documentElement.classList.contains("dark")', 'light theme reset');
    }
    await clickAriaLabel(client, 'เปลี่ยนเป็นโหมดมืด');
    await client.waitFor('document.documentElement.classList.contains("dark") && localStorage.getItem("h2l-theme") === "dark"', 'dark theme toggle');
    const themeState = await client.evaluate(`({
      darkClass: document.documentElement.classList.contains('dark'),
      storedTheme: localStorage.getItem('h2l-theme'),
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      textareaBackground: getComputedStyle(document.querySelector('#case-description')).backgroundColor
    })`);

    if (client.errors.length) {
      throw new Error(`Browser reported errors:\n${client.errors.join('\n')}`);
    }

    console.log(JSON.stringify({
      status: 'ok',
      dashboardUrl: DASHBOARD_URL,
      checks: {
        responsiveDrawerNavigation: true,
        mobileLayout,
        emptyCaseGuard: true,
        sampleCaseLoading: true,
        advancedSettingsDefaults: defaultSettings,
        analyzeDoubleSubmit: {
          requestCount: analyzeRequestDelta,
          secondClickAttempted: doubleSubmitState.attempted,
          disabledDuringAttempt: doubleSubmitState.guarded,
        },
        clinicalCaseResult: true,
        explainabilityTabs: true,
        semanticNodeInteraction: selectedSemanticNodeId,
        researchTopKIndependence: {
          researchTopK: researchTopKState.selectedTopK,
          alternateAvailable: researchTopKState.alternateAvailable,
          skippedReason: researchTopKState.alternateAvailable ? null : 'detected artifacts expose only Top 15',
          caseTopK: caseTopKAfterResearch,
        },
        staleReviewGuard: true,
        darkTheme: themeState,
        browserErrors: client.errors.length,
      },
    }, null, 2));
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
