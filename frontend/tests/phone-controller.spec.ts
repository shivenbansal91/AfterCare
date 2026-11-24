import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/tests/phone-controller-fixture.html");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"lastSync"');
});

test("offline dose survives restart and the personal workspace still loads with a pending outbox", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await page.getByRole("button", { name: "Record taken", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"pending":1');
  await page.reload();
  await page
    .getByRole("button", { name: "Load offline plans", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText('"status":"taken"');
  await expect(page.getByRole("status")).toContainText('"error":""');
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"pending":0');
  await expect(page.getByRole("status")).toContainText('"writes":1');
});

test("a lost acknowledgement retries the same dose without a duplicate server write", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Lose next reply", exact: true })
    .click();
  await page.getByRole("button", { name: "Record taken", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"pending":1');
  await expect(page.getByRole("status")).toContainText('"writes":1');
  await page.reload();
  await page
    .getByRole("button", { name: "Load offline plans", exact: true })
    .click();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"pending":0');
  await expect(page.getByRole("status")).toContainText('"writes":1');
});

test("an ambiguous plan edit pauses alarms and offline writes until the plan refreshes", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Enable reminders", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText('"alerts":1');
  await page.getByRole("button", { name: "Change plan", exact: true }).click();
  await expect(page.getByRole("status")).toContainText('"needsRefresh":true');
  await expect(page.getByRole("status")).toContainText('"alerts":0');
  await page.getByRole("button", { name: "Record taken", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Reconnect to verify your plan change",
  );
  await expect(page.getByRole("status")).toContainText('"pending":0');
});
