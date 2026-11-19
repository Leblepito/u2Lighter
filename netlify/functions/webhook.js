// Netlify Function: custom order webhook (JS port of automation/webhook_handler.py entry logic).
//
// Flow (must finish inside Netlify's ~10 s function limit):
//   1. validate the form payload
//   2. insert the order into Supabase with status "processing"
//   3. fire GitHub repository_dispatch (event_type "custom_order")
//   4. update the order to status "queued"
// The long-running part (Meshy.ai generation, model download, design pack, pipeline)
// runs in the "Custom Order" GitHub Actions workflow (.github/workflows/custom_order.yml).
//
// Netlify environment variables required:
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GH_DISPATCH_TOKEN (fine-grained PAT, Contents: read & write on the repo)
// Optional: GITHUB_REPO (default Leblepito/u2Lighter), WEBHOOK_SECRET (HMAC check when x-webhook-signature is sent)

const crypto = require("crypto");

const SUPABASE_URL = (process.env.SUPABASE_URL || "").replace(/\/+$/, "");
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const GH_TOKEN = process.env.GH_DISPATCH_TOKEN || process.env.GITHUB_TOKEN;
const GITHUB_REPO = process.env.GITHUB_REPO || "Leblepito/u2Lighter";
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET;

const PLINTH_COLORS = ["Pembe", "Siyah", "Fildisi", "Sari"];
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, x-webhook-signature",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function reply(statusCode, obj) {
  return { statusCode, headers: { ...CORS, "Content-Type": "application/json" }, body: JSON.stringify(obj) };
}

function verifySignature(rawBody, signature) {
  // Browser forms cannot hold a secret, so the check only applies when a signature is sent
  // (server-to-server callers). Unsigned requests from the public form are accepted.
  if (!signature || !WEBHOOK_SECRET) return true;
  const expected = crypto.createHmac("sha256", WEBHOOK_SECRET).update(rawBody).digest("hex");
  const a = Buffer.from(expected);
  const b = Buffer.from(String(signature));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function supabaseHeaders(extra = {}) {
  return {
    apikey: SUPABASE_KEY,
    Authorization: `Bearer ${SUPABASE_KEY}`,
    "Content-Type": "application/json",
    ...extra,
  };
}

async function insertOrder(row) {
  const resp = await fetch(`${SUPABASE_URL}/rest/v1/orders`, {
    method: "POST",
    headers: supabaseHeaders({ Prefer: "return=representation" }),
    body: JSON.stringify(row),
  });
  if (!resp.ok) throw new Error(`Supabase insert failed (${resp.status}): ${await resp.text()}`);
  const data = await resp.json();
  return Array.isArray(data) ? data[0] : data;
}

async function updateOrder(orderId, updates) {
  const resp = await fetch(`${SUPABASE_URL}/rest/v1/orders?order_id=eq.${encodeURIComponent(orderId)}`, {
    method: "PATCH",
    headers: supabaseHeaders({ Prefer: "return=minimal" }),
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error(`Supabase update failed (${resp.status}): ${await resp.text()}`);
}

async function triggerGithub(orderId) {
  if (!GH_TOKEN) throw new Error("GH_DISPATCH_TOKEN is not configured");
  const resp = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "u2lighter-webhook",
    },
    body: JSON.stringify({
      event_type: "custom_order",
      client_payload: { order_id: orderId, figure_id: `custom_${orderId}` },
    }),
  });
  if (resp.status !== 204) throw new Error(`GitHub dispatch failed (${resp.status}): ${await resp.text()}`);
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: CORS, body: "" };
  if (event.httpMethod !== "POST") return reply(405, { error: "Method not allowed" });
  if (!SUPABASE_URL || !SUPABASE_KEY) return reply(500, { error: "Supabase is not configured" });

  const rawBody = event.isBase64Encoded ? Buffer.from(event.body || "", "base64").toString("utf8") : event.body || "";
  const sig = (event.headers || {})["x-webhook-signature"];
  if (!verifySignature(rawBody, sig)) return reply(401, { error: "Invalid signature" });

  let data;
  try {
    data = JSON.parse(rawBody);
  } catch (_) {
    return reply(400, { error: "Invalid JSON" });
  }

  const email = String(data.email || "").trim();
  if (!email || !email.includes("@")) return reply(400, { error: "Valid email required" });
  const inputMethod = data.inputMethod;
  if (!["image", "prompt"].includes(inputMethod)) return reply(400, { error: "inputMethod must be 'image' or 'prompt'" });
  if (inputMethod === "prompt" && !String(data.prompt || "").trim()) return reply(400, { error: "Prompt is required" });
  if (inputMethod === "image" && !(typeof data.imageFile === "string" && data.imageFile.startsWith("data:image/"))) {
    return reply(400, { error: "Image (data URL) is required" });
  }

  const orderId = /^ORD-[A-Z0-9]{4,24}$/.test(data.order_id || "")
    ? data.order_id
    : `ORD-${crypto.randomBytes(4).toString("hex").toUpperCase()}`;

  const row = {
    order_id: orderId,
    customer_email: email,
    input_method: inputMethod,
    prompt: inputMethod === "prompt" ? String(data.prompt).slice(0, 2000) : null,
    image_b64: inputMethod === "image" ? data.imageFile : null,
    ref_images_b64: Array.isArray(data.refFiles) ? data.refFiles.filter((r) => typeof r === "string").slice(0, 3) : [],
    style: data.style || "panter",
    plinth_color: PLINTH_COLORS.includes(data.plinthColor) ? data.plinthColor : "Pembe",
    pins: /^\d+(,\d+)*$/.test(data.pins || "") ? data.pins : "8,4,2",
    plinth_height: /^\d+(\.\d+)?$/.test(String(data.plinthHeight || "")) ? String(data.plinthHeight) : "3.0",
    notes: String(data.notes || "").slice(0, 2000),
    status: "processing",
  };

  try {
    await insertOrder(row);
  } catch (e) {
    console.error(e);
    return reply(500, { error: "Could not save order" });
  }

  try {
    await triggerGithub(orderId);
    await updateOrder(orderId, { status: "queued", design_pack_path: `design_pack/custom_${orderId}.json` });
    return reply(200, { order_id: orderId, status: "queued", message: "Order queued for production" });
  } catch (e) {
    console.error(e);
    try {
      await updateOrder(orderId, { status: "failed", error_message: String(e.message || e).slice(0, 500) });
    } catch (_) {}
    return reply(502, { order_id: orderId, error: "Order saved but production could not be started" });
  }
};
