import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "./useApi";

describe("api.getState", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("hits GET /api/state and returns parsed JSON", async () => {
    const mockState = {
      version: "1",
      stage: "profiling",
      aim: "Understand churn",
      dataset_path: "data/customers.csv",
      last_saved: "2026-06-02T00:00:00Z",
      profile: null,
      plan: [],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockState),
      })
    );

    const result = await api.getState();

    expect(fetch).toHaveBeenCalledWith("/api/state", expect.objectContaining({ method: "GET" }));
    expect(result).toEqual(mockState);
  });

  it("throws an ApiError on non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: () =>
          Promise.resolve({
            error: "invalid_stage",
            message: "Action not valid for current stage.",
          }),
      })
    );

    await expect(api.getState()).rejects.toMatchObject({
      error: "invalid_stage",
      message: "Action not valid for current stage.",
    });
  });
});

describe("api.postSetup", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends a multipart/form-data POST to /api/setup", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ ok: true, session_id: "ses_abc" }),
      })
    );

    const file = new File(["col1,col2\n1,2"], "test.csv", { type: "text/csv" });
    await api.postSetup(file, "Understand churn");

    expect(fetch).toHaveBeenCalledWith("/api/setup", expect.objectContaining({ method: "POST" }));
    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(options.body).toBeInstanceOf(FormData);
    const fd = options.body as FormData;
    expect(fd.get("aim")).toBe("Understand churn");
    expect(fd.get("csv")).toEqual(file);
  });

  it("throws an ApiError on non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: "invalid_stage", message: "Not in setup stage." }),
      })
    );

    const file = new File(["col1\n1"], "test.csv", { type: "text/csv" });
    await expect(api.postSetup(file, "aim")).rejects.toMatchObject({
      error: "invalid_stage",
    });
  });
});

describe("api.postTurn", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends POST /api/turn with text in JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        json: () => Promise.resolve(null),
        text: () => Promise.resolve(""),
      })
    );

    await api.postTurn("please focus on churn by region");

    expect(fetch).toHaveBeenCalledWith(
      "/api/turn",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ text: "please focus on churn by region" }),
      })
    );
  });

  it("throws an ApiError on non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: "turn_busy", message: "Another turn is in flight." }),
      })
    );

    await expect(api.postTurn("text")).rejects.toMatchObject({ error: "turn_busy" });
  });
});

describe("api.postPlanUpdate", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends POST /api/plan/update with sections JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ ok: true }),
      })
    );

    const sections = [
      {
        id: "sec_01",
        title: "Overview",
        hypothesis: "Baseline",
        status: "queued" as const,
        py_path: null,
        png_path: null,
        md_path: null,
      },
    ];
    await api.postPlanUpdate(sections);

    expect(fetch).toHaveBeenCalledWith(
      "/api/plan/update",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ sections }),
      })
    );
  });
});

describe("api.postPlanAccept", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends POST /api/plan/accept with no body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        text: () => Promise.resolve(""),
      })
    );

    await api.postPlanAccept();

    expect(fetch).toHaveBeenCalledWith(
      "/api/plan/accept",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("api.postSectionAccept", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends POST /api/section/:id/accept", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        text: () => Promise.resolve(""),
      })
    );

    await api.postSectionAccept("sec_02");

    expect(fetch).toHaveBeenCalledWith(
      "/api/section/sec_02/accept",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("api.postSectionDrop", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends POST /api/section/:id/drop", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        text: () => Promise.resolve(""),
      })
    );

    await api.postSectionDrop("sec_03");

    expect(fetch).toHaveBeenCalledWith(
      "/api/section/sec_03/drop",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("api.getExport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends GET /api/export and returns text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve("# Brief\n\nContent here."),
      })
    );

    const result = await api.getExport();

    expect(fetch).toHaveBeenCalledWith("/api/export", expect.objectContaining({ method: "GET" }));
    expect(result).toBe("# Brief\n\nContent here.");
  });
});

describe("api.getFile", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends GET /api/file?path=... and returns text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve("import pandas as pd\n"),
      })
    );

    const result = await api.getFile("analyses/sec_01_overview.py");

    expect(fetch).toHaveBeenCalledWith(
      "/api/file?path=analyses%2Fsec_01_overview.py",
      expect.objectContaining({ method: "GET" })
    );
    expect(result).toBe("import pandas as pd\n");
  });

  it("throws ApiError on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ error: "missing_file", message: "File not found." }),
      })
    );

    await expect(api.getFile("analyses/missing.py")).rejects.toMatchObject({
      error: "missing_file",
    });
  });
});
