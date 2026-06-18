import {
  ApplicationCommandType,
  ChannelType,
  ChatInputCommandInteraction,
  Client,
  Events,
  GatewayIntentBits,
  GuildMember,
  Interaction,
  Message,
  MessageContextMenuCommandInteraction,
  MessageFlags,
  ModalBuilder,
  Partials,
  REST,
  Routes,
  SlashCommandBuilder,
  TextInputBuilder,
  TextInputStyle,
  ActionRowBuilder,
  ContextMenuCommandBuilder
} from "discord.js";
import { DatabaseSync } from "node:sqlite";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync } from "node:fs";

type Config = {
  token: string;
  clientId: string;
  guildId: string;
  adminUserIds: Set<string>;
  aiSettingsUserIds: Set<string>;
  allowGuildOwnerAdmin: boolean;
  databasePath: string;
  litellmBaseUrl: string;
  litellmApiKey: string;
};

type AiAccess =
  | { ok: true }
  | { ok: false; reason: "channel" | "role" };

const schema = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  parent_channel_id TEXT,
  author_id TEXT NOT NULL,
  author_name TEXT,
  content TEXT,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  edited_flag INTEGER NOT NULL DEFAULT 0,
  referenced_message_id TEXT,
  message_url TEXT,
  has_attachments INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
  message_id UNINDEXED,
  channel_id UNINDEXED,
  author_name,
  content,
  tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS attachments (
  attachment_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  last_seen_url TEXT,
  proxy_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachment_extractions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attachment_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  extracted_text TEXT,
  extraction_method TEXT,
  extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deleted_messages (
  message_id TEXT PRIMARY KEY,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  deleted_at TEXT NOT NULL,
  deletion_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_allowed_roles (
  role_id TEXT PRIMARY KEY,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_channel_whitelist (
  channel_id TEXT PRIMARY KEY,
  include_threads INTEGER NOT NULL DEFAULT 1,
  memory_enabled INTEGER NOT NULL DEFAULT 1,
  backfill_enabled INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_runtime_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_request_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  source_message_id TEXT,
  trigger_type TEXT NOT NULL,
  task_type TEXT NOT NULL,
  model_alias TEXT,
  fallback_chain TEXT,
  status TEXT NOT NULL,
  error_type TEXT,
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  actor_name TEXT,
  entrypoint TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  old_value TEXT,
  new_value TEXT,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
`;

class Store {
  readonly db: DatabaseSync;

  constructor(databasePath: string) {
    mkdirSync(dirname(databasePath), { recursive: true });
    this.db = new DatabaseSync(databasePath);
    this.db.exec("PRAGMA journal_mode = WAL");
    this.db.exec(schema);
  }

  listAllowedRoles(): string[] {
    return this.db.prepare("SELECT role_id FROM ai_allowed_roles ORDER BY role_id").all().map((row) => String((row as { role_id: unknown }).role_id));
  }

  listAllowedChannels(): string[] {
    return this.db.prepare("SELECT channel_id FROM ai_channel_whitelist ORDER BY channel_id").all().map((row) => String((row as { channel_id: unknown }).channel_id));
  }

  setting(key: string): string | undefined {
    return (this.db.prepare("SELECT value FROM ai_runtime_settings WHERE key = ?").get(key) as { value: string } | undefined)?.value;
  }

  addRole(roleId: string, actor: UserRef): boolean {
    const changed = this.db.prepare("INSERT OR IGNORE INTO ai_allowed_roles (role_id, created_by, created_at) VALUES (?, ?, ?)").run(roleId, actor.id, now()).changes > 0;
    this.audit(actor, "ai-settings", "allow_role", "role", roleId, changed ? null : roleId, roleId, changed ? "ok" : "no_change");
    return changed;
  }

  removeRole(roleId: string, actor: UserRef): boolean {
    const changed = this.db.prepare("DELETE FROM ai_allowed_roles WHERE role_id = ?").run(roleId).changes > 0;
    this.audit(actor, "ai-settings", "deny_role", "role", roleId, changed ? roleId : null, null, changed ? "ok" : "no_change");
    return changed;
  }

  addChannel(channelId: string, actor: UserRef): boolean {
    const changed = this.db.prepare(`
      INSERT OR IGNORE INTO ai_channel_whitelist
        (channel_id, include_threads, memory_enabled, backfill_enabled, created_by, created_at)
      VALUES (?, 1, 1, 1, ?, ?)
    `).run(channelId, actor.id, now()).changes > 0;
    this.audit(actor, "ai-settings", "allow_channel", "channel", channelId, changed ? null : channelId, channelId, changed ? "ok" : "no_change");
    return changed;
  }

  removeChannel(channelId: string, actor: UserRef): boolean {
    const changed = this.db.prepare("DELETE FROM ai_channel_whitelist WHERE channel_id = ?").run(channelId).changes > 0;
    this.audit(actor, "ai-settings", "deny_channel", "channel", channelId, changed ? channelId : null, null, changed ? "ok" : "no_change");
    return changed;
  }

  setRuntimeSetting(key: string, value: string, actor: UserRef): void {
    const oldValue = this.setting(key);
    this.db.prepare(`
      INSERT INTO ai_runtime_settings (key, value, updated_by, updated_at)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, updated_at = excluded.updated_at
    `).run(key, value, actor.id, now());
    this.audit(actor, "ai-settings", "set_runtime_setting", "setting", key, redact(key, oldValue), redact(key, value), "ok");
  }

  audit(actor: UserRef, entrypoint: string, action: string, targetType: string, targetId: string | null, oldValue: string | null, newValue: string | null, result: string): void {
    this.db.prepare(`
      INSERT INTO audit_logs
        (actor_id, actor_name, entrypoint, action, target_type, target_id, old_value, new_value, result, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(actor.id, actor.name, entrypoint, action, targetType, targetId, oldValue, newValue, result, now());
  }
}

type UserRef = { id: string; name: string | null };

export function parseIds(value = ""): Set<string> {
  return new Set(value.split(",").map((id) => id.trim()).filter(Boolean));
}

export function canUseAi(input: {
  channelIds: string[];
  userId: string;
  memberRoleIds: string[];
  allowedChannelIds: Set<string>;
  allowedRoleIds: Set<string>;
  aiSettingsUserIds: Set<string>;
}): AiAccess {
  if (!input.channelIds.some((id) => input.allowedChannelIds.has(id))) {
    return { ok: false, reason: "channel" };
  }
  if (input.aiSettingsUserIds.has(input.userId) || input.memberRoleIds.some((id) => input.allowedRoleIds.has(id))) {
    return { ok: true };
  }
  return { ok: false, reason: "role" };
}

export function safeMentions(text: string): string {
  return text.replace(/@(everyone|here|[!&]?\d{17,20})/g, "@\u200b$1");
}

export function splitDiscordText(text: string, limit = 2000): string[] {
  if (text.length <= limit) return [text];
  const chunks: string[] = [];
  const chunkLimit = Math.max(1, limit - Math.min(80, Math.floor(limit / 2)));
  for (let index = 0; index < text.length; index += chunkLimit) {
    chunks.push(text.slice(index, index + chunkLimit));
  }
  return chunks.map((chunk, index) => `[${index + 1}/${chunks.length}]\n${chunk}`);
}

function now(): string {
  return new Date().toISOString();
}

function redact(key: string, value?: string | null): string | null {
  if (value == null) return null;
  return key.toLowerCase().includes("key") ? "[redacted]" : value;
}

function loadConfig(): Config {
  try {
    process.loadEnvFile?.(".env");
  } catch {
    // .env is optional in containers.
  }

  return {
    token: requiredEnv("DISCORD_TOKEN"),
    clientId: requiredEnv("DISCORD_CLIENT_ID"),
    guildId: requiredEnv("DISCORD_GUILD_ID"),
    adminUserIds: parseIds(process.env.ADMIN_USER_IDS),
    aiSettingsUserIds: parseIds(process.env.AI_SETTINGS_USER_IDS),
    allowGuildOwnerAdmin: process.env.ALLOW_GUILD_OWNER_ADMIN !== "false",
    databasePath: databasePath(process.env.DATABASE_URL ?? "file:./data/bot.sqlite"),
    litellmBaseUrl: process.env.LITELLM_BASE_URL ?? "http://litellm:4000/v1",
    litellmApiKey: process.env.LITELLM_API_KEY ?? ""
  };
}

function requiredEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`${key} is required`);
  return value;
}

function databasePath(databaseUrl: string): string {
  return resolve(databaseUrl.startsWith("file:") ? databaseUrl.slice("file:".length) : databaseUrl);
}

function commands() {
  return [
    new SlashCommandBuilder()
      .setName("admin")
      .setDescription("Bot 管理入口"),
    new SlashCommandBuilder()
      .setName("settings")
      .setDescription("一般使用者設定入口"),
    new SlashCommandBuilder()
      .setName("ai-settings")
      .setDescription("AI / LLM 管理入口")
      .addSubcommand((subcommand) => subcommand.setName("overview").setDescription("顯示 AI 模組狀態"))
      .addSubcommand((subcommand) => subcommand.setName("allow-role").setDescription("允許角色使用 AI").addRoleOption((option) => option.setName("role").setDescription("Discord role").setRequired(true)))
      .addSubcommand((subcommand) => subcommand.setName("deny-role").setDescription("移除 AI 角色").addRoleOption((option) => option.setName("role").setDescription("Discord role").setRequired(true)))
      .addSubcommand((subcommand) => subcommand.setName("allow-channel").setDescription("允許頻道使用 AI").addChannelOption((option) => option.setName("channel").setDescription("Discord channel").setRequired(true)))
      .addSubcommand((subcommand) => subcommand.setName("deny-channel").setDescription("移除 AI 頻道白名單").addChannelOption((option) => option.setName("channel").setDescription("Discord channel").setRequired(true)))
      .addSubcommand((subcommand) => subcommand
        .setName("set-litellm")
        .setDescription("設定 LiteLLM 連線值")
        .addStringOption((option) => option.setName("base-url").setDescription("例如 http://litellm:4000/v1").setRequired(false))
        .addStringOption((option) => option.setName("api-key").setDescription("LiteLLM virtual key").setRequired(false))),
    new ContextMenuCommandBuilder()
      .setName("AI 分析這則訊息")
      .setType(ApplicationCommandType.Message),
    new ContextMenuCommandBuilder()
      .setName("AI 摘要上下文")
      .setType(ApplicationCommandType.Message),
    new ContextMenuCommandBuilder()
      .setName("AI 自訂提問")
      .setType(ApplicationCommandType.Message)
  ].map((command) => command.toJSON());
}

async function registerCommands(config: Config): Promise<void> {
  const rest = new REST({ version: "10" }).setToken(config.token);
  await rest.put(Routes.applicationGuildCommands(config.clientId, config.guildId), { body: commands() });
}

function isManager(interaction: Interaction, allowedIds: Set<string>, allowOwner: boolean): boolean {
  return allowedIds.has(interaction.user.id) || (allowOwner && interaction.guild?.ownerId === interaction.user.id);
}

function memberRoleIds(member: Interaction["member"] | Message["member"]): string[] {
  if (!member) return [];
  if (member instanceof GuildMember) return member.roles.cache.map((role) => role.id);
  return Array.isArray(member.roles) ? member.roles : [];
}

function channelScopeIds(channelId: string, parentId?: string | null): string[] {
  return parentId ? [channelId, parentId] : [channelId];
}

function parentChannelId(channel: Interaction["channel"] | Message["channel"]): string | null {
  return channel && "parentId" in channel ? channel.parentId : null;
}

function aiAccessForInteraction(interaction: Interaction, store: Store, config: Config): AiAccess {
  return canUseAi({
    channelIds: channelScopeIds(interaction.channelId ?? "", parentChannelId(interaction.channel)),
    userId: interaction.user.id,
    memberRoleIds: memberRoleIds(interaction.member),
    allowedChannelIds: new Set(store.listAllowedChannels()),
    allowedRoleIds: new Set(store.listAllowedRoles()),
    aiSettingsUserIds: config.aiSettingsUserIds
  });
}

function aiAccessForMessage(message: Message, store: Store, config: Config): AiAccess {
  return canUseAi({
    channelIds: channelScopeIds(message.channelId, parentChannelId(message.channel)),
    userId: message.author.id,
    memberRoleIds: memberRoleIds(message.member),
    allowedChannelIds: new Set(store.listAllowedChannels()),
    allowedRoleIds: new Set(store.listAllowedRoles()),
    aiSettingsUserIds: config.aiSettingsUserIds
  });
}

async function handleChatInput(interaction: ChatInputCommandInteraction, store: Store, config: Config): Promise<void> {
  if (interaction.commandName === "settings") {
    await interaction.reply({
      content: "Settings\n\n目前尚未開放可調整的個人設定。\n此入口保留給未來功能使用。",
      flags: MessageFlags.Ephemeral
    });
    return;
  }

  if (interaction.commandName === "admin") {
    if (!isManager(interaction, config.adminUserIds, config.allowGuildOwnerAdmin)) {
      await interaction.reply({ content: "你沒有使用 /admin 的權限。", flags: MessageFlags.Ephemeral });
      return;
    }
    await interaction.reply({
      content: `Bot Status\n\n版本：0.1.0\n資料庫：已連線\nGuild：${interaction.guildId}`,
      flags: MessageFlags.Ephemeral
    });
    return;
  }

  if (interaction.commandName !== "ai-settings") return;
  if (!isManager(interaction, config.aiSettingsUserIds, config.allowGuildOwnerAdmin)) {
    await interaction.reply({ content: "你沒有使用 /ai-settings 的權限。", flags: MessageFlags.Ephemeral });
    return;
  }

  const actor = { id: interaction.user.id, name: interaction.user.username };
  const subcommand = interaction.options.getSubcommand();

  if (subcommand === "overview") {
    await interaction.reply({ content: aiOverview(store, config), flags: MessageFlags.Ephemeral });
    return;
  }
  if (subcommand === "allow-role" || subcommand === "deny-role") {
    const role = interaction.options.getRole("role", true);
    const changed = subcommand === "allow-role" ? store.addRole(role.id, actor) : store.removeRole(role.id, actor);
    await interaction.reply({ content: `${changed ? "已更新" : "沒有變更"}：${role}`, flags: MessageFlags.Ephemeral });
    return;
  }
  if (subcommand === "allow-channel" || subcommand === "deny-channel") {
    const channel = interaction.options.getChannel("channel", true);
    const changed = subcommand === "allow-channel" ? store.addChannel(channel.id, actor) : store.removeChannel(channel.id, actor);
    await interaction.reply({ content: `${changed ? "已更新" : "沒有變更"}：${channel}`, flags: MessageFlags.Ephemeral });
    return;
  }
  if (subcommand === "set-litellm") {
    const baseUrl = interaction.options.getString("base-url");
    const apiKey = interaction.options.getString("api-key");
    if (!baseUrl && !apiKey) {
      await interaction.reply({ content: "沒有變更：請提供 base-url 或 api-key。", flags: MessageFlags.Ephemeral });
      return;
    }
    if (baseUrl) store.setRuntimeSetting("litellm_base_url", baseUrl, actor);
    if (apiKey) store.setRuntimeSetting("litellm_api_key", apiKey, actor);
    await interaction.reply({ content: "LiteLLM 設定已更新。", flags: MessageFlags.Ephemeral });
  }
}

function aiOverview(store: Store, config: Config): string {
  const roles = store.listAllowedRoles().map((id) => `<@&${id}>`).join("\n") || "尚未設定";
  const channels = store.listAllowedChannels().map((id) => `<#${id}>`).join("\n") || "尚未設定";
  const baseUrl = store.setting("litellm_base_url") ?? config.litellmBaseUrl;
  const hasKey = Boolean(store.setting("litellm_api_key") ?? config.litellmApiKey);
  return [
    "AI Overview",
    "",
    `LiteLLM Base URL：${baseUrl}`,
    `LiteLLM API Key：${hasKey ? "已設定" : "未設定"}`,
    "Model aliases：discord-text, discord-vision, discord-document",
    "",
    "AI Roles:",
    roles,
    "",
    "AI Channels:",
    channels
  ].join("\n");
}

async function handleMessageContext(interaction: MessageContextMenuCommandInteraction, store: Store, config: Config): Promise<void> {
  const access = aiAccessForInteraction(interaction, store, config);
  if (!access.ok) {
    await interaction.reply({
      content: access.reason === "channel" ? "此頻道尚未啟用 AI 功能" : "你沒有使用 AI 功能的權限",
      flags: MessageFlags.Ephemeral
    });
    return;
  }

  if (interaction.commandName === "AI 自訂提問") {
    const input = new TextInputBuilder()
      .setCustomId("question")
      .setLabel("補充問題")
      .setStyle(TextInputStyle.Paragraph)
      .setRequired(true);
    const modal = new ModalBuilder()
      .setCustomId(`ai-custom-question:${interaction.targetMessage.id}`)
      .setTitle("AI 自訂提問")
      .addComponents(new ActionRowBuilder<TextInputBuilder>().addComponents(input));
    await interaction.showModal(modal);
    return;
  }

  await interaction.reply({
    content: `${interaction.commandName} 已通過權限檢查；AI 管線會在第 4~5 階段接上。`,
    flags: MessageFlags.Ephemeral
  });
}

async function handleInteraction(interaction: Interaction, store: Store, config: Config): Promise<void> {
  if (interaction.isChatInputCommand()) {
    await handleChatInput(interaction, store, config);
    return;
  }
  if (interaction.isMessageContextMenuCommand()) {
    await handleMessageContext(interaction, store, config);
    return;
  }
  if (interaction.isModalSubmit() && interaction.customId.startsWith("ai-custom-question:")) {
    const access = aiAccessForInteraction(interaction, store, config);
    if (!access.ok) {
      await interaction.reply({
        content: access.reason === "channel" ? "此頻道尚未啟用 AI 功能" : "你沒有使用 AI 功能的權限",
        flags: MessageFlags.Ephemeral
      });
      return;
    }
    await interaction.reply({
      content: "自訂提問已收到；AI 管線會在第 4~5 階段接上。",
      flags: MessageFlags.Ephemeral
    });
  }
}

async function handleMention(message: Message, client: Client, store: Store, config: Config): Promise<void> {
  if (!message.guild || message.author.bot || !client.user || !message.mentions.has(client.user)) return;
  const access = aiAccessForMessage(message, store, config);
  if (!access.ok) {
    if (access.reason === "channel") {
      await message.reply({ content: "此頻道尚未啟用 AI 功能", allowedMentions: { parse: [], repliedUser: true } });
    }
    return;
  }
  await message.reply({
    content: safeMentions("AI 權限檢查已通過；LiteLLM 管線會在第 4 階段接上。"),
    allowedMentions: { parse: [], repliedUser: true }
  });
}

async function main(): Promise<void> {
  const config = loadConfig();
  const store = new Store(config.databasePath);
  await registerCommands(config);

  const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent],
    partials: [Partials.Channel]
  });

  client.once(Events.ClientReady, (readyClient) => {
    console.log(`Logged in as ${readyClient.user.tag}`);
  });
  client.on(Events.InteractionCreate, (interaction) => {
    handleInteraction(interaction, store, config).catch((error) => {
      console.error(error);
      if (interaction.isRepliable() && !interaction.replied && !interaction.deferred) {
        void interaction.reply({ content: "操作失敗，請稍後再試。", flags: MessageFlags.Ephemeral });
      }
    });
  });
  client.on(Events.MessageCreate, (message) => {
    handleMention(message, client, store, config).catch(console.error);
  });

  await client.login(config.token);
}

const isEntryPoint = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isEntryPoint) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
