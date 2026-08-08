/**
 * Shared-secret HTTP trigger for the-network. Hit via a phone home-screen Shortcut --
 * deliberately not SMS/Twilio (that cost ~$1-2/mo and broke the zero-cost requirement) and
 * not "ping any Claude app" (Claude mobile/web can't reach this at all -- see the plan).
 * No AI involved in the trigger path: the pipeline's own code already knows what to do,
 * this Worker's only job is "go."
 */

export interface Env {
  DEBOUNCE_KV: KVNamespace;
  TRIGGER_SECRET: string;
  GITHUB_PAT: string;
}

const DEBOUNCE_WINDOW_S = 60; // Twilio-era comment kept honest: GitHub retries dispatch
// deliveries too, so this guards against that as well as accidental double-taps.
const GITHUB_OWNER = "bricksx11";
const GITHUB_REPO = "the-network";
const DISPATCH_EVENT_TYPE = "sms-trigger"; // must match dispatch-post.yml's `types: [sms-trigger]`

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const providedSecret = request.headers.get("X-Trigger-Secret");
    if (!providedSecret || !timingSafeEqual(providedSecret, env.TRIGGER_SECRET)) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }

    const url = new URL(request.url);
    const scope = url.searchParams.get("scope") || "all";

    const debounceKey = `last-trigger:${scope}`;
    const alreadyTriggered = await env.DEBOUNCE_KV.get(debounceKey);
    if (alreadyTriggered) {
      return jsonResponse({
        ok: true,
        debounced: true,
        message: `Ignored -- scope=${scope} was already triggered within the last ${DEBOUNCE_WINDOW_S}s`,
      });
    }
    await env.DEBOUNCE_KV.put(debounceKey, String(Date.now()), { expirationTtl: DEBOUNCE_WINDOW_S });

    const dispatchResponse = await fetch(
      `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "the-network-trigger-worker",
        },
        body: JSON.stringify({
          event_type: DISPATCH_EVENT_TYPE,
          client_payload: { scope },
        }),
      },
    );

    if (!dispatchResponse.ok) {
      const errorBody = await dispatchResponse.text();
      return jsonResponse(
        { ok: false, error: `GitHub dispatch failed: ${dispatchResponse.status} ${errorBody}` },
        502,
      );
    }

    return jsonResponse({ ok: true, message: `Triggered scope=${scope}` });
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Constant-time string comparison so the shared secret can't be brute-forced via timing. */
export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
