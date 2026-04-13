import { describe, expect, it } from "vitest";
import {
  createAdminSessionToken,
  isValidAdminSession,
} from "@/lib/admin/session";

describe("admin session helpers", () => {
  it("accepts a freshly issued session token", async () => {
    const now = Date.now();
    const token = await createAdminSessionToken("secret", now);

    await expect(isValidAdminSession(token, "secret", now)).resolves.toBe(true);
  });

  it("rejects a token signed with another secret", async () => {
    const now = Date.now();
    const token = await createAdminSessionToken("secret", now);

    await expect(
      isValidAdminSession(token, "different-secret", now),
    ).resolves.toBe(false);
  });

  it("rejects expired tokens", async () => {
    const now = Date.now();
    const token = await createAdminSessionToken("secret", now);

    await expect(
      isValidAdminSession(token, "secret", now + 86_400_001),
    ).resolves.toBe(false);
  });

  it("rejects malformed tokens", async () => {
    await expect(
      isValidAdminSession("not-a-session-token", "secret"),
    ).resolves.toBe(false);
  });
});
