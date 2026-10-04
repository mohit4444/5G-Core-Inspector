// Synthetic UI fixtures only; these are not captured UE logs.
import { test, expect } from "@playwright/test";
const a = "imsi-001010123456780",
  b = "imsi-001010123456781";
function fixture() {
  const event = {
    type: "REGISTRATION_COMPLETED",
    timestamp: "2026-09-06T15:44:58.279",
    sessionId: "registration-1",
    state: "REGISTERED",
    timestampSource: "log",
    rawEvidence: "[gmm] Registration complete <img src=x onerror=alert(1)>",
  };
  const first = {
    sessionId: "registration-1",
    core: "open5gs",
    imsi: a,
    suci: "suci-test-a",
    state: "REGISTERED",
    registrationStatus: "SUCCESS",
    startedAt: "2026-09-06T15:44:57.741",
    completedAt: "2026-09-06T15:44:58.279",
    durationMs: 538,
    ranUeNgapId: 0,
    amfUeNgapId: 1,
    tac: 7,
    cellId: "0x66c000",
    networkFunctions: ["AMF", "SMF"],
    events: [event],
    pduSessions: [
      {
        id: "pdu-1",
        pduSessionId: 1,
        state: "IP_ASSIGNED",
        dnn: "internet",
        ipv4: "10.45.1.2",
        sst: 1,
        sd: "0xffffff",
        events: [],
      },
    ],
  };
  const second = {
    ...first,
    sessionId: "registration-2",
    imsi: b,
    suci: "suci-test-b",
    state: "DEREGISTERED",
    durationMs: 600,
    events: [],
    pduSessions: [],
  };
  return {
    health: {
      logSource: { connected: true, mode: "stdin", error: null },
      linesProcessed: 120,
      matchedEvents: 13,
      uncorrelatedLines: 1,
    },
    registrations: [first, second],
    ues: [
      {
        identity: a,
        imsi: a,
        suci: first.suci,
        state: first.state,
        sessionIds: [first.sessionId],
        latestSessionId: first.sessionId,
      },
      {
        identity: b,
        imsi: b,
        suci: second.suci,
        state: second.state,
        sessionIds: [second.sessionId],
        latestSessionId: second.sessionId,
      },
    ],
    registration: second,
    uncorrelated: [
      {
        timestamp: event.timestamp,
        reason: "Multiple compatible UEs",
        rawEvidence: "[gmm] Registration request",
      },
    ],
  };
}
async function mock(page, data, fail = () => false) {
  await page.route("**/api/*", (route) =>
    fail()
      ? route.fulfill({ status: 503, body: "Unavailable" })
      : route.fulfill({
          json: data[new URL(route.request().url()).pathname.split("/").at(-1)],
        }),
  );
}
test("switches UEs and displays their own PDU evidence", async ({ page }) => {
  await mock(page, fixture());
  await page.goto("");
  await expect(
    page.getByRole("button", { name: `Open ${b}`, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: a, exact: true }),
  ).toBeVisible();
  await expect(page.getByText("10.45.1.2", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Network functions involved", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("Log timestamp", { exact: true })).toHaveCount(0);
  await expect(page.getByText("0", { exact: true }).last()).toBeVisible();
  await expect(page.locator(".fields dd").first()).toHaveCSS(
    "font-size",
    "16px",
  );
  await expect(page.locator(".fields dd").first()).toHaveCSS(
    "color",
    "rgb(17, 24, 39)",
  );
  await expect(page.locator(".page-header")).toHaveCSS("width", "1280px");
  await expect(page.locator(".page-footer")).toHaveCSS("width", "1280px");
  await expect(
    page.getByRole("button", { name: "5G Core Inspector — Main screen" }),
  ).toBeVisible();
});
test("raw evidence is safe and stays expanded across polls", async ({
  page,
}) => {
  await mock(page, fixture());
  await page.goto("");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  await page
    .locator(".timeline-panel")
    .getByText("View raw evidence", { exact: true })
    .click();
  await expect(page.locator(".timeline-panel pre")).toContainText("<img src=x");
  await expect(page.locator("pre img")).toHaveCount(0);
  await page.waitForTimeout(1200);
  await expect(page.locator(".timeline-panel details")).toHaveAttribute(
    "open",
    "",
  );
  await page
    .getByRole("textbox", { name: "Search events" })
    .fill("not-in-fixture");
  await expect(
    page.getByRole("heading", { name: "No matching events" }),
  ).toBeVisible();
});
test("keeps uncorrelated evidence out of the primary UI", async ({ page }) => {
  await mock(page, fixture());
  await page.goto("");
  await expect(page.getByText(/Uncorrelated evidence/)).toHaveCount(0);
  await expect(page.getByText("Multiple compatible UEs")).toHaveCount(0);
});
test("retains last data and reports polling failures", async ({ page }) => {
  let failed = false;
  await mock(page, fixture(), () => failed);
  await page.goto("");
  await expect(
    page.getByRole("button", { name: `Open ${b}`, exact: true }),
  ).toBeVisible();
  failed = true;
  await expect(page.getByRole("alert")).toContainText(
    "Inspector connection interrupted",
  );
  await expect(
    page.getByRole("button", { name: `Open ${b}`, exact: true }),
  ).toBeVisible();
  await expect(page.locator(".connection")).toHaveText("Disconnected");
});
test("empty state remains clear and mobile has no horizontal overflow", async ({
  page,
}) => {
  const data = fixture();
  data.registrations = [];
  data.ues = [];
  data.registration = {
    state: "WAITING",
    registrationStatus: "WAITING",
    events: [],
    pduSessions: [],
  };
  data.health.linesProcessed = 0;
  data.health.logSource.connected = false;
  await mock(page, data);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("");
  await expect(
    page.getByRole("heading", { name: "Waiting for UE detection" }),
  ).toBeVisible();
  await expect(
    page.getByText("Waiting for core logs", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("attempt selection persists when new data arrives", async ({ page }) => {
  const data = fixture();
  const history = {
    ...data.registrations[0],
    sessionId: "registration-3",
    durationMs: 700,
    events: [],
  };
  data.registrations.push(history);
  data.ues[0].sessionIds.push(history.sessionId);
  data.ues[0].latestSessionId = history.sessionId;
  await mock(page, data);
  await page.goto("");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  await page.getByLabel("Registration attempt").selectOption("registration-1");
  const newest = { ...history, sessionId: "registration-4", durationMs: 900 };
  data.registrations.push(newest);
  data.ues[0].sessionIds.push(newest.sessionId);
  data.ues[0].latestSessionId = newest.sessionId;
  await page.waitForTimeout(1200);
  await expect(page.getByLabel("Registration attempt")).toHaveValue(
    "registration-1",
  );
  await expect(page.locator(".duration")).toContainText("538");
  await expect(
    page.getByLabel("Registration attempt").locator("option"),
  ).toHaveCount(3);
});

test("main screen searches observed identifiers and logo returns to the filtered list", async ({
  page,
}) => {
  const data = fixture();
  data.registrations[0].ranUeNgapId = 9817;
  await mock(page, data);
  await page.goto("");
  await expect(
    page.getByRole("heading", { name: "UE list", level: 2 }),
  ).toBeVisible();
  await expect(page.locator(".timeline-panel")).toHaveCount(0);
  const search = page.getByRole("textbox", { name: "Search UEs" });
  await search.fill("  SUCI-TEST-A  ");
  await expect(
    page.getByRole("button", { name: `Open ${a}`, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Open ${b}`, exact: true }),
  ).toHaveCount(0);
  await search.fill("no-such-identity");
  await expect(
    page.getByRole("heading", { name: "No matching UEs" }),
  ).toBeVisible();
  await search.fill("9817");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  await expect(page.locator(".timeline-panel")).toBeVisible();
  await page
    .getByRole("button", { name: "5G Core Inspector — Main screen" })
    .click();
  await expect(search).toHaveValue("9817");
  await expect(page.locator(".timeline-panel")).toHaveCount(0);
  await search.fill(b.slice(-6));
  await page.getByRole("button", { name: `Open ${b}`, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: b, exact: true }),
  ).toBeVisible();
  await expect(page.getByText("10.45.1.2", { exact: true })).toHaveCount(0);
});

test("failure details and timeline follow only the selected attempt on mobile", async ({
  page,
}) => {
  const data = fixture();
  const failed = {
    ...data.registrations[0],
    sessionId: "registration-3",
    state: "FAILED",
    registrationStatus: "FAILED",
    completedAt: null,
    pduSessions: [],
    failureStage: "SUBSCRIBER_IDENTIFICATION",
    diagnosisConfidence: "EXACT",
    failureReason: "Core could not find the subscriber for the SUCI",
    failureEvidence: {
      rawLogLine: "[gmm] Cannot find SUCI [404]",
      matchedRule: "suci_not_found",
    },
    events: [
      {
        type: "REGISTRATION_FAILED",
        sessionId: "registration-3",
        state: "FAILED",
        timestamp: "2026-09-06T15:45:10.000",
        rawEvidence: "[gmm] Cannot find SUCI [404]",
      },
    ],
  };
  data.registrations.push(failed);
  data.ues[0].sessionIds.push(failed.sessionId);
  data.ues[0].latestSessionId = failed.sessionId;
  data.ues[0].state = "FAILED";
  await mock(page, data);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Registration failure details",
  });
  await expect(panel).toContainText("subscriber record may be missing");
  await panel.getByText("Evidence from Open5GS", { exact: true }).click();
  await expect(panel.locator("pre")).toHaveText("[gmm] Cannot find SUCI [404]");
  await page.waitForTimeout(1200);
  await expect(panel.locator("details")).toHaveAttribute("open", "");
  await expect(page.locator(".timeline-panel")).not.toContainText(
    "Registration Completed",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("Registration attempt").selectOption("registration-1");
  await expect(panel).toHaveCount(0);
  await expect(page.locator(".timeline-panel h3")).toHaveText(
    "registration completed",
  );
  await expect(page.getByText("10.45.1.2", { exact: true })).toBeVisible();
  await page.getByLabel("Registration attempt").selectOption("registration-3");
  await expect(panel.locator("details")).not.toHaveAttribute("open", "");
});

test("identity enrichment preserves the selected UE and a missing UE does not switch to another", async ({
  page,
}) => {
  const data = fixture();
  data.ues[0].identity = "suci-test-a";
  data.ues[0].imsi = null;
  data.registrations[0].imsi = null;
  await mock(page, data);
  await page.goto("");
  await page
    .getByRole("button", { name: "Open suci-test-a", exact: true })
    .click();
  data.ues[0].identity = a;
  data.ues[0].imsi = a;
  data.registrations[0].imsi = a;
  await expect(
    page.getByRole("heading", { name: a, exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Registration attempt")).toHaveValue(
    "registration-1",
  );
  data.ues.shift();
  data.registrations.shift();
  await expect(
    page.getByRole("heading", { name: "UE no longer available" }),
  ).toBeVisible();
  await expect(page.locator(".timeline-panel")).toHaveCount(0);
});

test("timeout advice does not fabricate a core error or authentication cause", async ({
  page,
}) => {
  const data = fixture();
  Object.assign(data.registrations[0], {
    state: "FAILED",
    registrationStatus: "FAILED",
    completedAt: null,
    failureStage: "AFTER_REGISTRATION_REQUEST",
    diagnosisConfidence: "STAGE_LEVEL",
    failureReason: "Registration did not complete before timeout",
    failureEvidence: null,
    lastSuccessfulStage: "REGISTRATION_REQUEST_RECEIVED",
    durationMs: 30000,
    events: [
      {
        type: "REGISTRATION_REQUEST",
        sessionId: "registration-1",
        state: "REGISTRATION_IN_PROGRESS",
        rawEvidence: "[gmm] Registration request",
      },
      {
        type: "REGISTRATION_FAILED",
        sessionId: "registration-1",
        state: "FAILED",
        timestampSource: "timer",
        rawEvidence: null,
      },
    ],
  });
  await mock(page, data);
  await page.goto("");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Registration failure details",
  });
  await expect(panel).toContainText(
    "No explicit core failure message was observed",
  );
  await expect(panel).toContainText("completion logs may be missing");
  await expect(panel).not.toContainText("authentication settings");
  await panel.getByText("Timeout evidence", { exact: true }).click();
  await expect(panel.locator("pre").first()).toContainText(
    "No matching core failure log line",
  );
  await panel
    .getByText("Last observed Open5GS evidence", { exact: true })
    .click();
  await expect(panel.locator("pre").last()).toHaveText(
    "[gmm] Registration request",
  );
});

test("shows the evidence-backed failure diagnosis panel", async ({ page }) => {
  const data = fixture();
  const failed = {
    ...data.registrations[0],
    state: "FAILED",
    registrationStatus: "FAILED",
    lastSuccessfulStage: "REGISTRATION_REQUEST_RECEIVED",
    failureStage: "AUTHENTICATION",
    failureReason: "Authentication failed",
    protocolCause: null,
    diagnosisConfidence: "EXACT",
    durationMs: 742,
    failureEvidence: {
      rawLogLine: "[gmm] ERROR: Authentication failure",
      matchedRule: "authentication_failure",
    },
  };
  data.registrations = [failed];
  data.registration = failed;
  data.ues = [{ ...data.ues[0], state: "FAILED" }];
  await mock(page, data);
  await page.goto("");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Registration failure details",
  });
  await expect(panel).toContainText("Registration failed");
  await expect(panel).toContainText("AUTHENTICATION");
  await expect(panel).toContainText("REGISTRATION REQUEST RECEIVED");
  await expect(panel).toContainText("Not provided by core");
  await expect(panel).toContainText("742 ms");
  await expect(panel).toContainText("Observed failure");
  await expect(panel).toContainText("Possible causes");
  await expect(panel).toContainText("Suggested checks");
  await expect(panel).toContainText("not confirmed by this evidence");
  await panel.getByText("Evidence from Open5GS", { exact: true }).click();
  await expect(panel.locator("pre")).toContainText("Authentication failure");
});

test("automatically detected OAI labels the source and failure evidence", async ({ page }) => {
  const data = fixture();
  data.health.coreDetection = { status: "detected", core: "oai", label: "OAI 5G Core", adapterTarget: "v2.2.2" };
  Object.assign(data.registrations[0], {
    core: "oai", state: "FAILED", registrationStatus: "FAILED",
    failureStage: "AUTHENTICATION", failureReason: "Core initiated Authentication Reject",
    diagnosisConfidence: "EXACT", failureEvidence: {
      rawLogLine: "[2026-10-04 12:00:00.100] [amf_n1] [debug] Create Authentication Reject and send to UE",
    },
  });
  await mock(page, data);
  await page.goto("");
  await expect(page.locator(".refresh-note")).toContainText("OAI 5G Core");
  await expect(page.locator(".page-footer")).toContainText("OAI 5G Core log diagnostics");
  await page.getByRole("button", { name: `Open ${a}`, exact: true }).click();
  const panel = page.getByRole("region", { name: "Registration failure details" });
  await panel.getByText("Evidence from OAI 5G Core", { exact: true }).click();
  await expect(panel.locator("pre")).toContainText("Create Authentication Reject");
  await expect(panel).not.toContainText("Open5GS");
  await expect(panel).toContainText("Possible causes");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("unknown and mixed formats are visible without replacing existing results", async ({ page }) => {
  const data = fixture();
  data.health.coreDetection = { status: "waiting", message: "Waiting for a supported Open5GS or OAI log format." };
  await mock(page, data);
  await page.goto("");
  await expect(page.locator(".notice[role=status]")).toContainText("Core not identified yet");
  data.health.coreDetection = {
    status: "mixed", message: "Both Open5GS and OAI log formats were observed. Analysis is paused. Restart the Inspector with logs from one core deployment.",
  };
  await expect(page.getByRole("alert")).toContainText("Analysis is paused");
  await expect(page.getByRole("button", { name: `Open ${a}`, exact: true })).toBeVisible();
  await expect(page.locator(".page-footer")).toContainText("5G core log diagnostics");
});
