import assert from "node:assert/strict";
import test from "node:test";
import { canUseAi, parseIds, safeMentions, splitDiscordText } from "./index.js";

test("parseIds trims comma-separated env ids", () => {
  assert.deepEqual([...parseIds("1, 2,,3")], ["1", "2", "3"]);
});

test("AI access requires channel, then role or AI settings user", () => {
  const allowedChannelIds = new Set(["channel"]);
  const allowedRoleIds = new Set(["role"]);
  const aiSettingsUserIds = new Set(["owner"]);

  assert.deepEqual(canUseAi({ channelIds: ["other"], userId: "owner", memberRoleIds: [], allowedChannelIds, allowedRoleIds, aiSettingsUserIds }), { ok: false, reason: "channel" });
  assert.deepEqual(canUseAi({ channelIds: ["channel"], userId: "user", memberRoleIds: [], allowedChannelIds, allowedRoleIds, aiSettingsUserIds }), { ok: false, reason: "role" });
  assert.deepEqual(canUseAi({ channelIds: ["thread", "channel"], userId: "user", memberRoleIds: ["role"], allowedChannelIds, allowedRoleIds, aiSettingsUserIds }), { ok: true });
  assert.deepEqual(canUseAi({ channelIds: ["channel"], userId: "owner", memberRoleIds: [], allowedChannelIds, allowedRoleIds, aiSettingsUserIds }), { ok: true });
});

test("safeMentions prevents generated content from pinging everyone or ids", () => {
  assert.equal(safeMentions("@everyone <@123456789012345678> <@&123456789012345678>"), "@\u200beveryone <@\u200b123456789012345678> <@\u200b&123456789012345678>");
});

test("splitDiscordText adds chunk labels only when needed", () => {
  assert.deepEqual(splitDiscordText("short", 20), ["short"]);
  assert.deepEqual(splitDiscordText("x".repeat(25), 20), ["[1/3]\nxxxxxxxxxx", "[2/3]\nxxxxxxxxxx", "[3/3]\nxxxxx"]);
});
