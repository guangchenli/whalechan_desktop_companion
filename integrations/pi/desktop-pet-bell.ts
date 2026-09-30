/**
 * Pi extension: ring the desktop pet bell when a conversation round ends.
 *
 * 事件驱动，不依赖模型自觉：`agent_settled`（默认）在 Pi 完全停歇、等待输入时触发，
 * 直接写桌宠的本地 IPC 端点（和 mcp_server.py 用的是同一个 QLocalServer 端点），
 * 固定文案不消耗 token；默认的模型摘要会发一次旁路请求。
 *
 * 配置（可选，优先级从高到低）：
 *   1. 环境变量 DESKTOP_PET_SOCKET（套接字名或绝对路径）、DESKTOP_PET_DIR（桌宠项目目录）
 *   2. <cwd>/.pi/desktop-pet.json
 *   3. ~/.pi/agent/desktop-pet.json
 *
 * {
 *   "projectDir": "/home/phil/dev/desktop_companion",  // 用于推导 IPC 端点
 *   "socket": "desktop-pet-xxxxxxxx",                  // 或直接指定端点名/路径
 *   "event": "agent_settled",                          // agent_settled | turn_end | off
 *   "title": "Pi",                                     // 气泡标题，默认用会话名
 *   "sound": false,                                    // 是否同时请求系统蜂鸣
 *   "durationSeconds": 12,
 *   "ringOnError": true,
 *   "ringOnAbort": false,
 *   "debounceMs": 1500,
 *   "warn": true,                                      // 失败时提示一次
 *   "summary": {                                       // 让模型写一两句总结（不进会话上下文）
 *     "enabled": true,
 *     "maxChars": 90,                                  // 气泡里总结的长度上限
 *     "maxTokens": 512,
 *     "temperature": 0.2,
 *     "timeoutMs": 15000,
 *     "minInputChars": 60,                             // 最后回复短于此长度直接用固定文案，不花 token
 *     "prompt": "",                                    // 覆盖注入的总结指令
 *     "noThinking": false,                             // 默认沿用会话思考级别；true 时请求关闭思考，可能影响缓存
 *     "samplingParams": {}                              // 直接指定合并进请求体的字段
 *   }
 * }
 *
 * 总结怎么发的：取 `agent_before_settle` 给出的上下文快照 `context.llmMessages`，拼上 Pi 刚发过的
 * 同一份 system prompt 与同一组工具声明，再在末尾追加一条“请用一两句总结你刚才的回复”的注入请求，
 * 沿用会话思考级别与 sessionId 发一次 `modelRegistry.complete()`，尽量复用 KV cache；
 * 结果只用来填气泡，不写回会话、不进 transcript、下一轮看不到，天然丢弃。
 *
 * 命令行：`pi --no-pet-bell` 关闭 bell；`pi --pet-bell-plain` 只发固定文案（不发总结调用）；
 * `/pet-bell [on|off|status|plain|测试文本]`（status 会显示上次总结的 cache 命中情况）。
 */

import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { uuidv7 } from "@earendil-works/pi-ai";
import type { Context, Message } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type RingEvent = "agent_settled" | "turn_end" | "off";
type Outcome = "completed" | "aborted" | "error";

interface Settings {
	projectDir?: string;
	socket?: string;
	event?: RingEvent;
	title?: string;
	sound?: boolean;
	durationSeconds?: number;
	ringOnError?: boolean;
	ringOnAbort?: boolean;
	debounceMs?: number;
	warn?: boolean;
	doneText?: string;
	abortedText?: string;
	errorText?: string;
	summary?: {
		enabled?: boolean;
		maxChars?: number;
		maxTokens?: number;
		temperature?: number;
		timeoutMs?: number;
		minInputChars?: number;
		prompt?: string;
		/** Extra request body fields for the bypass call, merged into the request body as-is. */
		samplingParams?: Record<string, unknown>;
		/**
		 * Default false preserves the session's thinking level. True requests no thinking;
		 * changes to the rendered template may reduce cache reuse, depending on the server.
		 */
		noThinking?: boolean;
	};
}

const MAX_MESSAGE = 2000;
const MAX_TITLE = 60;

function readJson(file: string): Settings {
	try {
		const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
		return parsed && typeof parsed === "object" ? (parsed as Settings) : {};
	} catch {
		return {};
	}
}

/** Mirrors getpass.getuser(): env first, then the passwd entry. */
function userName(): string {
	for (const key of ["LOGNAME", "USER", "LNAME", "USERNAME"]) {
		const value = process.env[key];
		if (value !== undefined) return value;
	}
	try {
		return os.userInfo().username;
	} catch {
		return "";
	}
}

/** Same derivation as pet_ipc.default_server_name(). */
function socketNameForProject(projectDir: string): string | undefined {
	try {
		const real = fs.realpathSync(path.resolve(projectDir));
		const identity = `${real}:${userName()}`;
		return `desktop-pet-${crypto.createHash("sha256").update(identity).digest("hex").slice(0, 20)}`;
	} catch {
		return undefined;
	}
}

/** Find the desktop_companion checkout from an mcp.json that serves the pet. */
function projectDirFromMcpConfig(cwd: string): string | undefined {
	const configs = [
		path.join(os.homedir(), ".pi", "agent", "mcp.json"),
		path.join(cwd, ".pi", "mcp.json"),
	];
	for (const file of configs) {
		let raw: unknown;
		try {
			raw = JSON.parse(fs.readFileSync(file, "utf8"));
		} catch {
			continue;
		}
		const servers = (raw as { mcpServers?: Record<string, { command?: string; args?: string[] }> })
			.mcpServers;
		for (const server of Object.values(servers ?? {})) {
			const argv = [server?.command, ...(server?.args ?? [])].filter(
				(arg): arg is string => typeof arg === "string",
			);
			for (const arg of argv) {
				if (path.basename(arg) !== "mcp_server.py") continue;
				const dir = path.dirname(path.resolve(arg));
				if (fs.existsSync(path.join(dir, "pet_ipc.py"))) return dir;
			}
		}
	}
	return undefined;
}

/** A symlinked installation still identifies the checkout that owns this extension. */
function projectDirFromExtension(): string | undefined {
	try {
		const source = fs.realpathSync(fileURLToPath(import.meta.url));
		const projectDir = path.resolve(path.dirname(source), "../..");
		return fs.existsSync(path.join(projectDir, "pet_ipc.py")) ? projectDir : undefined;
	} catch {
		return undefined;
	}
}

/** QLocalServer endpoint for a bare name lives in Qt's temp dir (QDir::tempPath()). */
function endpointFor(name: string): string {
	if (name.startsWith("/") || name.startsWith("\\\\.\\pipe\\")) return name;
	if (process.platform === "win32") return `\\\\.\\pipe\\${name}`;
	return path.join(os.tmpdir(), name);
}

/** Same per-user directory as pet_ipc.discovery_directory(). */
function discoveryDirectory(): string {
	const user = crypto.createHash("sha256").update(userName()).digest("hex").slice(0, 20);
	return path.join(os.tmpdir(), `desktop-pet-discovery-${user}`);
}

async function discoverEndpoint(): Promise<string | undefined> {
	const directory = discoveryDirectory();
	const candidates: { endpoint: string; startedAt: number }[] = [];
	try {
		const owner = fs.lstatSync(directory);
		if (!owner.isDirectory()) return undefined;
		if (process.platform !== "win32" && owner.uid !== os.userInfo().uid) return undefined;
		for (const file of fs.readdirSync(directory, { withFileTypes: true })) {
			if (!file.isFile() || !file.name.endsWith(".json")) continue;
			try {
				const target = path.join(directory, file.name);
				if (fs.statSync(target).size > 16384) continue;
				const record = JSON.parse(fs.readFileSync(target, "utf8"));
				if (record?.version !== 1 || typeof record.endpoint !== "string" || !record.endpoint) continue;
				if (!path.isAbsolute(record.endpoint) && !record.endpoint.startsWith("\\\\.\\pipe\\")) continue;
				if (typeof record.startedAt !== "number" || !Number.isFinite(record.startedAt)) continue;
				candidates.push({ endpoint: record.endpoint, startedAt: record.startedAt });
			} catch {
				// Ignore stale, incomplete or incompatible records.
			}
		}
	} catch {
		return undefined;
	}
	const ordered = candidates.sort((a, b) => b.startedAt - a.startedAt || a.endpoint.localeCompare(b.endpoint));
	// Probe independently, so many stale files do not multiply the timeout.
	const ready = await Promise.all(ordered.map(async ({ endpoint }) => {
		try {
			const reply = await requestPet(endpoint, { command: "status" }, 300);
			return reply.ok && reply.running === true;
		} catch {
			return false;
		}
	}));
	return ordered.find((_candidate, index) => ready[index])?.endpoint;
}

interface BellResult {
	ok: boolean;
	error?: string;
	status?: string;
	running?: boolean;
}

function requestPet(
	socketPath: string,
	payload: Record<string, unknown>,
	timeoutMs = 2000,
): Promise<BellResult> {
	return new Promise((resolve) => {
		let settled = false;
		const finish = (result: BellResult) => {
			if (settled) return;
			settled = true;
			socket.destroy();
			resolve(result);
		};
		const socket = net.connect(socketPath);
		let buffer = "";
		socket.setTimeout(timeoutMs);
		socket.on("connect", () => socket.write(`${JSON.stringify(payload)}\n`));
		socket.on("data", (chunk) => {
			buffer += chunk.toString("utf8");
			const newline = buffer.indexOf("\n");
			if (newline < 0) return;
			try {
				const reply = JSON.parse(buffer.slice(0, newline)) as {
					ok?: boolean;
					error?: string;
					result?: { status?: string; running?: boolean };
				};
				finish(
					reply?.ok
						? { ok: true, status: reply.result?.status, running: reply.result?.running }
						: { ok: false, error: reply?.error || "桌宠拒绝通知" },
				);
			} catch {
				finish({ ok: false, error: "桌宠响应格式错误" });
			}
		});
		socket.on("timeout", () => finish({ ok: false, error: "桌宠响应超时" }));
		socket.on("error", (err) => finish({ ok: false, error: (err as Error).message }));
		socket.on("close", () => finish({ ok: false, error: "桌宠未确认通知" }));
	});
}

function collapse(text: string): string {
	return text.replace(/\s+/g, " ").trim();
}

/** True when the provider stopped the reply because the user cancelled it. */
function abortedByUser(message: unknown): boolean {
	return (message as { stopReason?: string })?.stopReason === "aborted";
}

/** Flatten the text blocks of a user or assistant message. */
function textOf(message: unknown): string {
	const content = (message as { content?: unknown })?.content;
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter(
			(block): block is { type: "text"; text: string } =>
				!!block &&
				typeof block === "object" &&
				block.type === "text" &&
				typeof block.text === "string",
		)
		.map((block) => block.text)
		.join(" ");
}

const SUMMARY_PROMPT =
	"（Pi 扩展的旁路请求，不是用户的新问题，也不会写回会话。）请用一到两句、不超过 60 字的话，总结你上一条回复的结论：刚做完了什么，或正在等用户提供什么。使用与用户相同的语言，只输出总结本身，不要前缀、客套、引号、markdown 或列表。不要推理、不要草稿、不要复述上文，直接输出总结本身。";

interface SummaryUsage {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
}

interface RoundSnapshot {
	outcome: Outcome;
	context: Context;
	model: ExtensionContext["model"];
	reasoningEffort: Exclude<ExtensionContext["thinkingLevel"], "off">;
	text: string;
	sessionId: string;
}

/** Even a provider that ignores abort must not keep the bell waiting past its deadline. */
async function withAbort<T>(request: Promise<T>, signal: AbortSignal): Promise<T> {
	const onAbort = () => rejectAbort(new Error("摘要请求已取消或超时"));
	let rejectAbort: (error: Error) => void;
	const aborted = new Promise<never>((_resolve, reject) => {
		rejectAbort = reject;
	});
	signal.addEventListener("abort", onAbort, { once: true });
	try {
		if (signal.aborted) onAbort();
		return await Promise.race([request, aborted]);
	} finally {
		signal.removeEventListener("abort", onAbort);
	}
}

/** Set DESKTOP_PET_BELL_DEBUG=/path/to/log to inspect KV cache reuse and sent text. */
function debugLog(text: string): void {
	const target = process.env.DESKTOP_PET_BELL_DEBUG;
	if (!target) return;
	try {
		fs.appendFileSync(target, `${new Date().toISOString()} ${text}\n`);
	} catch {
		// Diagnostics must never break the bell.
	}
}

/** Keep the model output to one clean line without decoration. */
function cleanSummary(raw: string): string {
	const firstLines = raw
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter(Boolean)
		.slice(0, 2)
		.join(" ");
	return collapse(firstLines)
		.replace(/^(总结|摘要|概要)\s*[:：]\s*/, "")
		.replace(/^[-*>•\s]+/, "")
		.replace(/^["“”'`]+|["“”'`]+$/g, "")
		.trim();
}

export default function (pi: ExtensionAPI) {
	let settings: Settings = {};
	let socketPath: string | undefined;
	let enabled = true;
	let lastRingAt = 0;
	let warned = false;
	let lastAssistantAborted = false;
	let round: RoundSnapshot | undefined;
	let revision = 0;
	let activeSummary: AbortController | undefined;
	let summaryUsage: SummaryUsage | undefined;
	let summaryError: string | undefined;

	pi.registerFlag("no-pet-bell", {
		description: "Disable desktop pet bell notifications for this session",
		type: "boolean",
		default: false,
	});

	pi.registerFlag("pet-bell-plain", {
		description: "Send the fixed bell text instead of a model-written summary",
		type: "boolean",
		default: false,
	});

	async function configure(ctx: ExtensionContext) {
		settings = {
			...readJson(path.join(os.homedir(), ".pi", "agent", "desktop-pet.json")),
			...readJson(path.join(ctx.cwd, ".pi", "desktop-pet.json")),
		};
		socketPath = await resolveEndpoint(ctx, settings);
	}

	async function resolveEndpoint(ctx: ExtensionContext, config: Settings): Promise<string | undefined> {
		const socket = process.env.DESKTOP_PET_SOCKET || config.socket;
		if (socket) return endpointFor(socket);
		const explicitProject = process.env.DESKTOP_PET_DIR || config.projectDir;
		if (explicitProject) {
			const name = socketNameForProject(explicitProject);
			return name ? endpointFor(name) : undefined;
		}
		const discovered = await discoverEndpoint();
		if (discovered) return discovered;
		const projectDir =
			projectDirFromMcpConfig(ctx.cwd) ||
			(fs.existsSync(path.join(ctx.cwd, "pet_ipc.py")) ? ctx.cwd : undefined) ||
			projectDirFromExtension();
		const name = projectDir ? socketNameForProject(projectDir) : undefined;
		return name ? endpointFor(name) : undefined;
	}

	function fixedText(outcome: Outcome, config: Settings): string {
		return outcome === "error"
			? config.errorText ?? "⚠️ Pi 运行出错"
			: outcome === "aborted"
				? config.abortedText ?? "⏹ Pi 已停止"
				: config.doneText ?? "✅ Pi 已完成，等待输入";
	}

	/** Provider-facing tool declarations, in the order Pi declares them. */
	function toolDeclarations() {
		const order = new Map(pi.getActiveTools().map((name, index) => [name, index]));
		return pi
			.getAllTools()
			.filter((tool) => order.has(tool.name))
			.sort((a, b) => (order.get(a.name) ?? 0) - (order.get(b.name) ?? 0))
			.map((tool) => ({ name: tool.name, description: tool.description, parameters: tool.parameters }));
	}

	function sessionIdOf(ctx: ExtensionContext): string {
		const manager = ctx.sessionManager as unknown as { getSessionId?: () => string };
		return manager.getSessionId?.() ?? ctx.sessionManager.getHeader()?.id ?? uuidv7();
	}

	function cancelPending() {
		revision++;
		activeSummary?.abort();
		activeSummary = undefined;
	}

	function captureRound(ctx: ExtensionContext, outcome: Outcome, messages: Message[]): RoundSnapshot {
		// Copy the boundary context before another turn or extension can mutate it.
		const transcript = structuredClone(messages);
		const last = transcript[transcript.length - 1];
		const cancelled =
			outcome === "aborted" || ctx.signal?.aborted === true || lastAssistantAborted || abortedByUser(last);
		const carriesSystem = transcript[0]?.role === "system";
		return {
			outcome: cancelled ? "aborted" : outcome,
			context: carriesSystem
				? { messages: transcript }
				: { systemPrompt: ctx.getSystemPrompt(), tools: structuredClone(toolDeclarations()), messages: transcript },
			model: ctx.model,
			reasoningEffort: ctx.thinkingLevel === "off" ? undefined : ctx.thinkingLevel,
			text: last?.role === "assistant" ? textOf(last) : "",
			sessionId: sessionIdOf(ctx),
		};
	}

	/**
	 * Append a summary request to a per-round context snapshot, retaining the thinking level
	 * and session affinity for cache reuse. Nothing is written back to the conversation.
	 */
	async function summarize(
		ctx: ExtensionContext,
		snapshot: RoundSnapshot,
		cfg: NonNullable<Settings["summary"]>,
		isCurrent: () => boolean,
	): Promise<string | undefined> {
		if (cfg.enabled === false || pi.getFlag("pet-bell-plain") === true) return undefined;
		const model = snapshot.model;
		if (!model || !snapshot.text.trim()) return undefined;
		if (collapse(snapshot.text).length < (cfg.minInputChars ?? 60)) return undefined;

		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), cfg.timeoutMs ?? 15000);
		activeSummary = controller;
		summaryError = undefined;
		try {
			const injected = {
				role: "user" as const,
				content: [{ type: "text" as const, text: cfg.prompt || SUMMARY_PROMPT }],
				timestamp: Date.now(),
			};
			const context: Context = { ...snapshot.context, messages: [...snapshot.context.messages, injected] };
			const response = await withAbort(
				ctx.modelRegistry.complete(model, context, {
					// Reasoning and the answer share max_tokens; an empty answer falls back to fixed text.
					// This generation budget does not change the input prefix.
					maxTokens: cfg.maxTokens ?? 512,
					temperature: cfg.temperature ?? 0.2,
					reasoningEffort: cfg.noThinking === true ? undefined : snapshot.reasoningEffort,
					// Merge extra fields; the explicit noThinking switch takes precedence for effort.
					samplingParams: {
						...cfg.samplingParams,
						...(cfg.noThinking === true ? { reasoning_effort: "none" } : {}),
					},
					signal: controller.signal,
					sessionId: snapshot.sessionId,
				}),
				controller.signal,
			);
			if (!isCurrent()) return undefined;
			if (response.stopReason === "error" || response.stopReason === "aborted") {
				throw new Error(response.errorMessage || `摘要请求 ${response.stopReason}`);
			}
			const usage = response.usage;
			summaryUsage = {
				input: usage?.input ?? 0,
				output: usage?.output ?? 0,
				cacheRead: usage?.cacheRead ?? 0,
				cacheWrite: usage?.cacheWrite ?? 0,
			};
			debugLog(
				`summary model=${model.id} prefix=${snapshot.context.messages[0]?.role === "system" ? "transcript" : "systemPrompt+tools"}` +
					` cacheRead=${summaryUsage.cacheRead} cacheWrite=${summaryUsage.cacheWrite}` +
					` input=${summaryUsage.input} output=${summaryUsage.output}`,
			);
			const text = cleanSummary(
				response.content
					.filter((block) => block.type === "text")
					.map((block) => (block as { text?: string }).text ?? "")
					.join(" "),
			);
			return text ? text.slice(0, cfg.maxChars ?? 90) : undefined;
		} catch (error) {
			if (!isCurrent()) return undefined;
			summaryError = error instanceof Error ? error.message : String(error);
			debugLog(`summary failed: ${summaryError}`);
			return undefined;
		} finally {
			clearTimeout(timer);
			if (activeSummary === controller) activeSummary = undefined;
		}
	}

	async function ring(
		ctx: ExtensionContext,
		override?: { message?: string; force?: boolean },
	): Promise<BellResult | undefined> {
		if (!enabled || pi.getFlag("no-pet-bell") === true) return undefined;
		const event: RingEvent = settings.event ?? "agent_settled";
		if (!override?.force && event === "off") return undefined;
		const config = { ...settings, summary: { ...settings.summary } };
		const snapshot = round;
		const outcome = snapshot?.outcome ?? "completed";
		const title = (collapse(config.title || pi.getSessionName() || "Pi") || "Pi").slice(0, MAX_TITLE);

		if (!override?.force) {
			if (!snapshot) return undefined;
			if (outcome === "aborted" && config.ringOnAbort !== true) return undefined;
			if (outcome === "error" && config.ringOnError === false) return undefined;
			const debounce = config.debounceMs ?? 1500;
			const now = Date.now();
			if (now - lastRingAt < debounce) return undefined;
			lastRingAt = now;
		}
		cancelPending();
		const taskRevision = revision;
		const isCurrent = () => revision === taskRevision && enabled && pi.getFlag("no-pet-bell") !== true;
		const endpoint = await resolveEndpoint(ctx, config);
		if (!isCurrent()) return undefined;
		socketPath = endpoint;
		if (!endpoint) {
			warnOnce(ctx, "未找到桌宠 IPC 端点：请启动桌宠，或设置 DESKTOP_PET_SOCKET / desktop-pet.json 的 projectDir");
			return undefined;
		}

		// One short line: a model-written status when enabled, otherwise the fixed text.
		const summary =
			override?.message || outcome !== "completed" || !snapshot
				? undefined
				: await summarize(ctx, snapshot, config.summary, isCurrent);
		if (!isCurrent()) return undefined;
		const message = (override?.message ?? summary ?? fixedText(outcome, config))
			.replace(/[\r\n]+/g, " ")
			.slice(0, MAX_MESSAGE);

		const result = await requestPet(endpoint, {
			command: "bell",
			message,
			title,
			duration_seconds: config.durationSeconds ?? 12,
			sound: config.sound === true,
		});
		debugLog(`bell ok=${result.ok} title=${JSON.stringify(title)} message=${JSON.stringify(message)}`);
		if (!result.ok && isCurrent()) warnOnce(ctx, `桌宠 bell 失败：${result.error}`);
		return result;
	}

	/**
	 * In the TUI the summary request runs in the background so typing stays responsive;
	 * one-shot `pi -p` must await it or the process exits before the bell is sent.
	 */
	function ringNow(ctx: ExtensionContext): Promise<unknown> | undefined {
		const task = ring(ctx).catch((error) => {
			debugLog(`bell failed: ${error instanceof Error ? error.message : String(error)}`);
		});
		return ctx.mode === "print" || ctx.mode === "json" ? task : undefined;
	}

	function warnOnce(ctx: ExtensionContext, text: string) {
		if (warned) return;
		warned = true;
		if (settings.warn !== false && ctx.hasUI) ctx.ui.notify(`${text}（/pet-bell status 查看）`, "warning");
	}

	pi.on("session_start", async (_event, ctx) => {
		cancelPending();
		round = undefined;
		lastAssistantAborted = false;
		lastRingAt = 0;
		enabled = true;
		warned = false;
		summaryUsage = undefined;
		summaryError = undefined;
		await configure(ctx);
	});
	pi.on("session_shutdown", async () => {
		cancelPending();
		round = undefined;
	});
	pi.on("session_before_switch", async () => { cancelPending(); });
	pi.on("session_before_fork", async () => { cancelPending(); });
	pi.on("session_before_tree", async () => { cancelPending(); });
	pi.on("agent_start", async () => {
		cancelPending();
		round = undefined;
		lastAssistantAborted = false;
	});

	// The current run can report cancellation as an error at its final boundary.
	pi.on("agent_end", async (event) => {
		lastAssistantAborted = false;
		for (let i = event.messages.length - 1; i >= 0; i--) {
			const message = event.messages[i] as { role?: string };
			if (message?.role !== "assistant") continue;
			// Remember the stop reason: a cancelled reply is a user abort, not a failure.
			lastAssistantAborted = abortedByUser(message);
			break;
		}
	});

	pi.on("turn_end", async (event, ctx) => {
		lastAssistantAborted = abortedByUser(event.message);
		if ((settings.event ?? "agent_settled") === "turn_end") {
			cancelPending();
			round = captureRound(ctx, event.outcome, event.context.llmMessages);
			await ringNow(ctx);
		}
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		if ((settings.event ?? "agent_settled") === "agent_settled") {
			round = captureRound(ctx, event.outcome, event.context.llmMessages);
		}
	});

	// Final, notification-only boundary: Pi will not retry, compact, or continue on its own.
	pi.on("agent_settled", async (_event, ctx) => {
		if ((settings.event ?? "agent_settled") === "agent_settled") await ringNow(ctx);
	});

	pi.registerCommand("pet-bell", {
		description: "桌宠 bell：/pet-bell [on|off|status|plain|自定义文本]",
		handler: async (args, ctx) => {
			const arg = args.trim();
			if (arg === "off") {
				enabled = false;
				cancelPending();
				ctx.ui.notify("桌宠 bell 已关闭（本会话）", "info");
				return;
			}
			if (arg === "on") {
				enabled = true;
				warned = false;
				ctx.ui.notify("桌宠 bell 已开启", "info");
				return;
			}
			if (arg === "status") {
				socketPath = await resolveEndpoint(ctx, settings);
				const event = settings.event ?? "agent_settled";
				const summary =
					settings.summary?.enabled === false || pi.getFlag("pet-bell-plain") === true
						? "固定文案"
						: summaryUsage
							? `cache 读 ${summaryUsage.cacheRead}/写 ${summaryUsage.cacheWrite}/新 ${summaryUsage.input}/出 ${summaryUsage.output}`
							: "未调用";
				ctx.ui.notify(
					`端点 ${socketPath ?? "未解析"}｜事件 ${event}｜${enabled ? "开启" : "关闭"}｜总结 ${summary}` +
						(summaryError ? `｜上次失败 ${summaryError}` : ""),
					socketPath ? "info" : "warning",
				);
				return;
			}
			if (arg === "plain") {
				cancelPending();
				settings.summary = { ...settings.summary, enabled: settings.summary?.enabled === false };
				ctx.ui.notify(
					settings.summary.enabled ? "已开启模型总结" : "已关闭模型总结，改用固定文案",
					"info",
				);
				return;
			}
			warned = false;
			const result = await ring(ctx, { message: arg || "🔔 Pi 测试 bell", force: true });
			if (result) {
				ctx.ui.notify(
					result.ok ? `桌宠已接收（${result.status ?? "ok"}）` : `发送失败：${result.error}`,
					result.ok ? "info" : "error",
				);
			}
		},
	});
}
