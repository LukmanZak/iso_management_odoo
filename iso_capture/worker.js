"use strict";

const { chromium } = require("playwright-core");
const base = process.env.ISO_CAPTURE_ODOO_URL || "http://odoo:8069";
const db = process.env.ISO_CAPTURE_DB || "sales";
const login = process.env.ISO_CAPTURE_LOGIN || "";
const password = process.env.ISO_CAPTURE_PASSWORD || "";
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function rpc(context, path, params, timeout = 30000) {
  const response = await context.request.post(base + path, {
    data: { jsonrpc: "2.0", method: "call", id: 1, params },
    timeout,
  });
  if (!response.ok()) throw new Error(`Odoo HTTP ${response.status()}`);
  const body = await response.json();
  if (body.error) throw new Error(body.error.data?.message || body.error.message || "Odoo request failed");
  return body.result;
}

async function scanCall(context, method, args = []) {
  return rpc(context, "/web/dataset/call_kw/iso.management.scan/" + method, {
    model: "iso.management.scan", method, args, kwargs: {},
  }, method === "execute_scan" ? 900000 : 30000);
}

async function call(context, method, args = []) {
  return rpc(context, "/web/dataset/call_kw/iso.management.evidence/" + method, {
    model: "iso.management.evidence", method, args, kwargs: {},
  });
}

async function protectUnreadableFields(page, allowedFields) {
  const blocked = await page.evaluate(fields => {
    const allowed = new Set(Array.isArray(fields) ? fields : []);
    return Array.from(document.querySelectorAll(".o_field_widget[name], .o_field_cell[name], .o_data_cell[data-name]")).filter(node => {
      const fieldName = node.getAttribute("name") || node.getAttribute("data-name");
      return fieldName && !allowed.has(fieldName) && !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    }).map(node => node.getAttribute("name") || node.getAttribute("data-name"));
  }, allowedFields);
  if (blocked.length) {
    console.log("Blocked fields: " + [...new Set(blocked)].join(", "));
    throw new Error("SOURCE_PAGE_FIELD_ACCESS_DENIED");
  }
}

function userFacingError(error) {
  const message = String(error?.message || error || "");
  const relatedRecord = message.match(/SOURCE_PAGE_ACCESS_DENIED:([^\n]+)/i)?.[1]?.trim();
  if (relatedRecord) {
    return `This Odoo page also needs access to related ${relatedRecord} records, which the capture account cannot read. The original source link is still available.`;
  }
  if (/SOURCE_PAGE_ACCESS_DENIED/i.test(message)) {
    return "This Odoo page needs access to related app records that the capture account cannot read. The original source link is still available.";
  }
  if (/SOURCE_PAGE_FIELD_ACCESS_DENIED/i.test(message)) {
    return "The page contains fields the original scanner cannot read. Open the source link with an authorized account.";
  }
  if (/SOURCE_PAGE_NOT_RENDERED/i.test(message)) {
    return "Odoo could not render a full record page for this source. The original source link is still available.";
  }
  if (/not allowed|access error|access denied|forbidden|permission/i.test(message)) {
    return "The capture account could not open this Odoo page. The original source link is still available.";
  }
  if (/timeout|o_form_view|o_list_view|record page/i.test(message)) {
    return "Odoo did not render a record page for this source. The original source link is still available.";
  }
  if (/screenshot|image|too large/i.test(message)) {
    return "The full-page screenshot could not be saved. Retry the capture; the original source link is still available.";
  }
  return "The Odoo page could not be captured. Retry the screenshot; the original source link is still available.";
}

async function capturePage(page, job) {
  if (!/^[a-z][a-z0-9_.]*$/.test(job.model) || !/^[a-z][a-z0-9_]*$/.test(job.field) || !Number.isSafeInteger(job.record_id)) {
    throw new Error("Invalid source page route");
  }

  const url = `${base}/odoo/${job.model}/${job.record_id}?cids=${job.company_id}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForFunction(() => {
    const visible = element => !!element && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
    return [...document.querySelectorAll(".o_form_view, .o_list_view, .o_dialog, .o_error_dialog")].some(visible);
  }, null, { timeout: 12000 }).catch(async () => {
    throw new Error("SOURCE_PAGE_NOT_RENDERED");
  });

  const dialogTexts = await page.locator(".o_dialog, .o_error_dialog").allTextContents().catch(() => []);
  const accessDialog = dialogTexts.find(text => /access error|not allowed to access|does not have ['’]read['’] access/i.test(text));
  if (accessDialog) {
    const related = accessDialog.match(/not allowed to access ['’]([^'’]+)['’]/i)?.[1];
    throw new Error(`SOURCE_PAGE_ACCESS_DENIED:${related || "related records"}`);
  }
  if (!(await page.locator(".o_form_view, .o_list_view").first().isVisible().catch(() => false))) {
    throw new Error("SOURCE_PAGE_NOT_RENDERED");
  }

  const route = new URL(page.url());
  if (!route.pathname.includes(`/odoo/${job.model}/${job.record_id}`)) {
    throw new Error("Odoo did not open the requested source record page");
  }

  await protectUnreadableFields(page, job.allowed_fields || []);
  await page.waitForTimeout(500);

  let image = await page.screenshot({ fullPage: true, type: "jpeg", quality: 72, scale: "css", animations: "disabled", timeout: 45000 });
  if (image.length > 10 * 1024 * 1024) {
    image = await page.screenshot({ fullPage: true, type: "jpeg", quality: 48, scale: "css", animations: "disabled", timeout: 45000 });
  }
  if (image.length > 10 * 1024 * 1024) throw new Error("Full-page screenshot exceeds 10 MB");
  return { image };
}

async function run() {
  if (!login || !password) {
    console.error("Set ISO_CAPTURE_LOGIN and ISO_CAPTURE_PASSWORD for the read-only capture account.");
    while (true) await delay(60000);
  }
  while (true) {
    let browser;
    try {
      browser = await chromium.launch({ headless: true, executablePath: "/usr/bin/chromium", args: ["--no-sandbox"] });
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
      const session = await rpc(context, "/web/session/authenticate", { db, login, password });
      if (!session || !session.uid) throw new Error("Capture account authentication failed");
      const page = await context.newPage();
      while (true) {
        const scanJob = await scanCall(context, "claim_scan");
        if (scanJob) {
          await scanCall(context, "execute_scan", [scanJob.id, scanJob.token]);
          console.log(`Finished searching for scan ${scanJob.id}`);
          continue;
        }
        const job = await call(context, "capture_next");
        if (!job) { await delay(5000); continue; }
        try {
          const { image } = await capturePage(page, job);
          await call(context, "capture_finish", [job.id, image.toString("base64"), false, true]);
          console.log(`Captured unaltered Odoo page for evidence ${job.id}`);
        } catch (error) {
          const message = String(error.message || error).slice(0, 400);
          await call(context, "capture_finish", [job.id, false, userFacingError(error)]);
          console.error(`Capture ${job.id} failed: ${message}`);
        }
      }
    } catch (error) {
      console.error(`Capture worker will reconnect: ${String(error.message || error).slice(0, 200)}`);
      if (browser) await browser.close().catch(() => {});
      await delay(15000);
    }
  }
}

run().catch(error => { console.error(error.message); process.exit(1); });
