import { beforeEach, describe, expect, it, vi } from "vitest";
import worker, { timingSafeEqual } from "../src/index";
import type { Env } from "../src/index";

describe("timingSafeEqual", () => {
  it("returns true for identical strings", () => {
    expect(timingSafeEqual("secret123", "secret123")).toBe(true);
  });

  it("returns false for different strings of the same length", () => {
    expect(timingSafeEqual("secret123", "secret124")).toBe(false);
  });

  it("returns false for different-length strings", () => {
    expect(timingSafeEqual("short", "muchlongersecret")).toBe(false);
  });

  it("returns false when compared against an empty string", () => {
    expect(timingSafeEqual("secret", "")).toBe(false);
  });
});

function makeFakeKV(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  return {
    get: vi.fn(async (key: string) => store.get(key) ?? null),
    put: vi.fn(async (key: string, value: string, _opts?: unknown) => {
      store.set(key, value);
    }),
  } as unknown as KVNamespace;
}

function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    DEBOUNCE_KV: makeFakeKV(),
    TRIGGER_SECRET: "correct-secret",
    GITHUB_PAT: "fake-pat",
    ...overrides,
  };
}

describe("worker fetch handler", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 401 when the secret header is missing", async () => {
    const env = makeEnv();
    const request = new Request("https://trigger.example/");
    const response = await worker.fetch(request, env);
    expect(response.status).toBe(401);
  });

  it("returns 401 when the secret is wrong", async () => {
    const env = makeEnv();
    const request = new Request("https://trigger.example/", {
      headers: { "X-Trigger-Secret": "wrong-secret" },
    });
    const response = await worker.fetch(request, env);
    expect(response.status).toBe(401);
  });

  it("fires repository_dispatch and returns ok on a fresh trigger", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    const env = makeEnv();
    const request = new Request("https://trigger.example/", {
      headers: { "X-Trigger-Secret": "correct-secret" },
    });

    const response = await worker.fetch(request, env);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toMatchObject({ ok: true, message: "Triggered scope=all" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.github.com/repos/bricksx11/the-network/dispatches");
    expect(init?.headers).toMatchObject({ Authorization: "Bearer fake-pat" });
    const sentBody = JSON.parse(init?.body as string);
    expect(sentBody).toEqual({ event_type: "sms-trigger", client_payload: { scope: "all" } });

    expect(env.DEBOUNCE_KV.put).toHaveBeenCalledWith(
      "last-trigger:all",
      expect.any(String),
      { expirationTtl: 60 },
    );
  });

  it("passes through a specific scope from the query string", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    const env = makeEnv();
    const request = new Request("https://trigger.example/?scope=Barber", {
      headers: { "X-Trigger-Secret": "correct-secret" },
    });

    const response = await worker.fetch(request, env);
    const body = await response.json();

    expect(body).toMatchObject({ ok: true, message: "Triggered scope=Barber" });
    expect(env.DEBOUNCE_KV.put).toHaveBeenCalledWith("last-trigger:Barber", expect.any(String), expect.anything());
  });

  it("debounces a duplicate trigger within the window without calling GitHub", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    const env = makeEnv({ DEBOUNCE_KV: makeFakeKV({ "last-trigger:all": String(Date.now()) }) });
    const request = new Request("https://trigger.example/", {
      headers: { "X-Trigger-Secret": "correct-secret" },
    });

    const response = await worker.fetch(request, env);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toMatchObject({ ok: true, debounced: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 502 when GitHub's dispatch call fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("bad credentials", { status: 401 }),
    );
    const env = makeEnv();
    const request = new Request("https://trigger.example/", {
      headers: { "X-Trigger-Secret": "correct-secret" },
    });

    const response = await worker.fetch(request, env);
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toMatchObject({ ok: false });
  });
});
