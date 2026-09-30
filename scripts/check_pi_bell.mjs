/** Regression checks with mocked model/IPC; --real-discovery is used by the isolated Qt test. */
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let piEntry;
try {
	piEntry = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
} catch {
	// Locate a global Pi install through its executable without launching npm or Pi.
	for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
		const executable = path.join(dir, process.platform === "win32" ? "pi.cmd" : "pi");
		if (!fs.existsSync(executable)) continue;
		let root = path.dirname(fs.realpathSync(executable));
		while (root !== path.dirname(root)) {
			const manifest = path.join(root, "package.json");
			if (fs.existsSync(manifest) && JSON.parse(fs.readFileSync(manifest, "utf8")).name === "@earendil-works/pi-coding-agent") {
				piEntry = path.join(root, "dist/index.js");
				break;
			}
			root = path.dirname(root);
		}
		if (piEntry) break;
	}
	assert.ok(piEntry, "Install Pi locally or put its executable on PATH before running this check.");
}
const piRequire = createRequire(piEntry);
const { transform } = await import(pathToFileURL(piRequire.resolve("esbuild")));
const piAiDir = piRequire.resolve.paths("@earendil-works/pi-ai")
	.map((dir) => path.join(dir, "@earendil-works/pi-ai/dist"))
	.find((dir) => fs.existsSync(path.join(dir, "index.js")));
assert.ok(piAiDir, "Pi's pi-ai package was not found.");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "check-pi-bell-"));
const packets = [];
// Import mocks isolate user configuration and prevent notifications reaching the real desktop pet.
globalThis.petBellTestOs = { ...os, homedir: () => tmp, tmpdir: () => tmp };
const offlineEndpoints = new Set();
globalThis.petBellTestNet = {
	connect(endpoint) {
		const socket = new EventEmitter();
		socket.setTimeout = () => {};
		socket.destroy = () => {};
		socket.write = (text) => {
			const request = JSON.parse(text);
			packets.push({ endpoint, ...request });
			const result = request.command === "status" ? { running: !offlineEndpoints.has(endpoint) } : { status: "queued" };
			queueMicrotask(() => socket.emit("data", Buffer.from(`${JSON.stringify({ ok: true, result })}\n`)));
		};
		queueMicrotask(() => socket.emit("connect"));
		return socket;
	},
};
for (const key of ["DESKTOP_PET_SOCKET", "DESKTOP_PET_DIR", "DESKTOP_PET_BELL_DEBUG"]) delete process.env[key];

const source = fs.readFileSync(path.join(repo, "integrations/pi/desktop-pet-bell.ts"), "utf8");
globalThis.petBellTestExtensionUrl = pathToFileURL(path.join(repo, "integrations/pi/desktop-pet-bell.ts")).href;
const compiled = await transform(source, { loader: "ts", format: "esm" });
let code = compiled.code;
for (const [original, replacement] of [
	['import net from "node:net";', "const net = globalThis.petBellTestNet;"],
	['import os from "node:os";', "const os = globalThis.petBellTestOs;"],
	['import { uuidv7 } from "@earendil-works/pi-ai";', 'const uuidv7 = () => "test-session";'],
	["fileURLToPath(import.meta.url)", "fileURLToPath(globalThis.petBellTestExtensionUrl)"],
]) {
	assert.ok(code.includes(original), `Missing mock import: ${original}`);
	code = code.replace(original, replacement);
}
const factory = (await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`)).default;
const flush = () => new Promise((resolve) => setImmediate(resolve));
const assistant = () => ({ role: "assistant", content: [{ type: "text", text: "完成任务。".repeat(25) }], stopReason: "stop" });
const response = (text = "任务完成") => ({ content: [{ type: "text", text }], stopReason: "stop", usage: {} });
function deferred() {
	let resolve;
	const promise = new Promise((done) => { resolve = done; });
	return { promise, resolve };
}

async function setup(config = {}, complete = () => response()) {
	packets.length = 0;
	offlineEndpoints.clear();
	const handlers = {}, commands = {}, calls = [], notices = [];
	const writeConfig = (next) => {
		fs.mkdirSync(path.join(tmp, ".pi"), { recursive: true });
		fs.writeFileSync(path.join(tmp, ".pi/desktop-pet.json"), JSON.stringify({ socket: "test-pet", debounceMs: 0, ...next }));
	};
	writeConfig(config);
	const pi = {
		on(name, fn) { handlers[name] = fn; },
		registerCommand(name, command) { commands[name] = command; },
		registerFlag() {}, getFlag() { return false; }, getSessionName() { return "Original"; },
		getActiveTools() { return []; }, getAllTools() { return []; },
	};
	const ctx = {
		cwd: tmp, mode: "print", hasUI: false, thinkingLevel: "low", model: { id: "mock" },
		ui: { notify(text) { notices.push(text); } },
		sessionManager: { getSessionId() { return "test-session"; } },
		getSystemPrompt() { return "Original system"; },
		modelRegistry: { async complete(model, context, options) {
			calls.push({ model, context, options });
			return complete(calls.length);
		} },
	};
	factory(pi);
	const emit = async (name, event = {}) => handlers[name]?.(event, ctx);
	const command = async (text) => commands["pet-bell"].handler(text, ctx);
	const boundary = (outcome = "completed", message = assistant()) => ({ outcome, message, context: { llmMessages: [{ role: "user", content: "任务" }, message] } });
	await emit("session_start");
	await emit("agent_start");
	const event = boundary();
	await emit("agent_end", { messages: [event.message] });
	await emit("agent_before_settle", event);
	return { ctx, pi, emit, command, boundary, event, calls, notices, writeConfig };
}

let passed = 0;
async function check(name, run) {
	await run();
	passed++;
	console.log(`PASS ${name}`);
}

try {
	if (process.argv[2] === "--real-discovery") {
		// The Python check supplies an isolated registry and a real Qt server to contact.
		globalThis.petBellTestNet.connect = (await import("node:net")).connect;
		globalThis.petBellTestOs.tmpdir = () => process.argv[3];
		const copied = path.join(tmp, "copied-extension.ts");
		fs.writeFileSync(copied, source);
		globalThis.petBellTestExtensionUrl = pathToFileURL(copied).href;
		const s = await setup({ socket: undefined, summary: { enabled: false } });
		await s.command("status");
		assert.ok(s.notices.at(-1).includes(process.argv[4]), s.notices.at(-1));
		await s.emit("agent_settled");
		console.log("PASS copied extension discovers and notifies a real Qt IPC server");
	} else {
		await check("copied extension discovers latest live endpoint and preserves explicit overrides", async () => {
			const user = ["LOGNAME", "USER", "LNAME", "USERNAME"].map((key) => process.env[key])
				.find((value) => value !== undefined) ?? os.userInfo().username;
			const userHash = crypto.createHash("sha256").update(user).digest("hex").slice(0, 20);
			const registry = path.join(tmp, `desktop-pet-discovery-${userHash}`);
			fs.mkdirSync(registry, { mode: 0o700 });
			const copied = path.join(tmp, "copied-extension.ts");
			fs.writeFileSync(copied, source);
			globalThis.petBellTestExtensionUrl = pathToFileURL(copied).href;
			const old = path.join(tmp, "old-pet"), latest = path.join(tmp, "latest-pet"), stale = path.join(tmp, "stale-pet");
			for (const [index, endpoint] of [old, latest, stale].entries()) {
				fs.writeFileSync(path.join(registry, `${index}.json`), JSON.stringify({ version: 1, endpoint, startedAt: index + 1 }));
			}
			fs.writeFileSync(path.join(registry, "broken.json"), "{");
			fs.writeFileSync(path.join(registry, "unsupported.json"), JSON.stringify({ version: 2, endpoint: stale, startedAt: 100 }));
			try {
				const s = await setup({ socket: undefined, summary: { enabled: false } });
				offlineEndpoints.add(stale);
				await s.emit("agent_settled");
				assert.equal(packets.filter((packet) => packet.command === "bell").at(-1).endpoint, latest);
				offlineEndpoints.add(latest);
				await s.emit("agent_settled");
				assert.equal(packets.filter((packet) => packet.command === "bell").at(-1).endpoint, old);
				const explicit = await setup({ socket: "explicit-pet", summary: { enabled: false } });
				await explicit.emit("agent_settled");
				assert.equal(packets.length, 1);
				assert.equal(packets[0].endpoint, path.join(tmp, "explicit-pet"));
			} finally {
				fs.rmSync(registry, { recursive: true, force: true });
				globalThis.petBellTestExtensionUrl = pathToFileURL(path.join(repo, "integrations/pi/desktop-pet-bell.ts")).href;
			}
		});
		await check("symlink install finds checkout from an unrelated cwd without configuration", async () => {
			const installed = path.join(tmp, "installed-extension.ts");
			fs.symlinkSync(path.join(repo, "integrations/pi/desktop-pet-bell.ts"), installed);
			globalThis.petBellTestExtensionUrl = pathToFileURL(installed).href;
			try {
				const s = await setup({ socket: undefined, summary: { enabled: false } });
				await s.emit("agent_settled");
				assert.equal(packets.length, 1);
				assert.match(packets[0].endpoint, /desktop-pet-[a-f0-9]{20}$/);
			} finally {
				globalThis.petBellTestExtensionUrl = pathToFileURL(path.join(repo, "integrations/pi/desktop-pet-bell.ts")).href;
			}
		});
		await check("Pi native loader preserves extension location through a symlink", async () => {
			const fixture = path.join(tmp, "fixture");
			const extension = path.join(fixture, "integrations/pi/desktop-pet-bell.ts");
			fs.mkdirSync(path.dirname(extension), { recursive: true });
			fs.writeFileSync(path.join(fixture, "pet_ipc.py"), "# Endpoint discovery fixture\n");
			// Only isolate the home directory; import.meta.url is handled by Pi's real loader.
			fs.writeFileSync(extension, source.replace('import os from "node:os";', "const os = globalThis.petBellTestOs;"));
			const installed = path.join(tmp, "native-extension.ts");
			fs.symlinkSync(extension, installed);
			fs.rmSync(path.join(tmp, ".pi/desktop-pet.json"), { force: true });
			const { loadExtensions } = await import(pathToFileURL(path.join(path.dirname(piEntry), "core/extensions/loader.js")));
			const loaded = await loadExtensions([installed], tmp);
			assert.deepEqual(loaded.errors, []);
			assert.equal(loaded.extensions.length, 1);
			const notices = [];
			const ctx = { cwd: tmp, ui: { notify(text) { notices.push(text); } } };
			const native = loaded.extensions[0];
			for (const handler of native.handlers.get("session_start")) await handler({}, ctx);
			await native.commands.get("pet-bell").handler("status", ctx);
			const user = ["LOGNAME", "USER", "LNAME", "USERNAME"].map((key) => process.env[key])
				.find((value) => value !== undefined) ?? os.userInfo().username;
			const hash = crypto.createHash("sha256").update(`${fs.realpathSync(fixture)}:${user}`).digest("hex").slice(0, 20);
			assert.ok(notices[0].includes(`desktop-pet-${hash}`), notices[0]);
		});
		await check("error preference only filters errors", async () => {
			const s = await setup({ ringOnError: false, summary: { enabled: false } });
			await s.emit("agent_settled");
			assert.equal(packets.length, 1);
			await s.emit("agent_before_settle", s.boundary("error"));
			await s.emit("agent_settled");
			assert.equal(packets.length, 1);
		});
		await check("turn_end and settled event modes ring once", async () => {
			for (const event of ["turn_end", "agent_settled"]) {
				const s = await setup({ event, summary: { enabled: false } });
				await s.emit("turn_end", s.event);
				await s.emit("agent_settled");
				assert.equal(packets.length, 1);
			}
		});
		await check("cancellation uses abort preference and text", async () => {
			for (const ringOnAbort of [false, true]) {
				const s = await setup({ ringOnAbort, summary: { enabled: false } });
				const message = { ...assistant(), stopReason: "aborted" };
				await s.emit("agent_end", { messages: [message] });
				await s.emit("agent_before_settle", s.boundary("error", message));
				await s.emit("agent_settled");
				assert.equal(packets.length, ringOnAbort ? 1 : 0);
				if (ringOnAbort) assert.equal(packets[0].message, "⏹ Pi 已停止");
			}
		});
		await check("aborted signal normalizes an error outcome", async () => {
			const s = await setup({ ringOnAbort: true });
			s.ctx.signal = AbortSignal.abort();
			await s.emit("agent_before_settle", s.boundary("error"));
			await s.emit("agent_settled");
			assert.equal(packets[0].message, "⏹ Pi 已停止");
			assert.equal(s.calls.length, 0);
		});
		await check("summary inherits thinking, session and 512-token budget", async () => {
			const s = await setup();
			await s.emit("agent_settled");
			assert.equal(s.calls[0].options.maxTokens, 512);
			assert.equal(s.calls[0].options.reasoningEffort, "low");
			assert.equal(s.calls[0].options.sessionId, "test-session");
			assert.equal(packets[0].message, "任务完成");
		});
		await check("session thinking off stays off", async () => {
			const s = await setup();
			s.ctx.thinkingLevel = "off";
			await s.emit("agent_before_settle", s.event);
			await s.emit("agent_settled");
			assert.equal(s.calls[0].options.reasoningEffort, undefined);
		});
		await check("turn_end summarizes the current turn before agent_end", async () => {
			const s = await setup({ event: "turn_end" });
			const message = { ...assistant(), content: [{ type: "text", text: "本回合的新结论。".repeat(10) }] };
			await s.emit("turn_end", s.boundary("completed", message));
			assert.equal(s.calls[0].context.messages.at(-2).content[0].text, message.content[0].text);
		});
		await check("noThinking merges fields and overrides explicit effort", async () => {
			for (const samplingParams of [{}, { top_p: 0.8, reasoning_effort: "high" }]) {
				const s = await setup({ summary: { noThinking: true, samplingParams } });
				await s.emit("agent_settled");
				assert.equal(s.calls[0].options.reasoningEffort, undefined);
				assert.deepEqual(s.calls[0].options.samplingParams, { ...samplingParams, reasoning_effort: "none" });
			}
		});
		await check("leading system snapshot stays intact and is copied", async () => {
			const s = await setup();
			const event = s.boundary();
			event.context.llmMessages.unshift({ role: "system", content: "Captured system", toolsAdded: [] });
			await s.emit("agent_before_settle", event);
			event.context.llmMessages[0].content = "Changed system";
			s.ctx.thinkingLevel = "high";
			s.ctx.getSystemPrompt = () => "Changed system";
			await s.emit("agent_settled");
			assert.equal(s.calls[0].context.messages[0].content, "Captured system");
			assert.equal(s.calls[0].context.systemPrompt, undefined);
			assert.equal(s.calls[0].context.tools, undefined);
			assert.equal(s.calls[0].options.reasoningEffort, "low");
			assert.equal(event.context.llmMessages.length, 3);
		});
		await check("off aborts pending summary; on does not revive it", async () => {
			const pending = deferred();
			const s = await setup({}, () => pending.promise);
			s.ctx.mode = "tui";
			await s.emit("agent_settled");
			await s.command("off");
			assert.ok(s.calls[0].options.signal.aborted);
			await s.command("on");
			pending.resolve(response("旧摘要"));
			await flush();
			assert.equal(packets.length, 0);
		});
		await check("new run cancels old work without cancelling its replacement", async () => {
			const first = deferred(), second = deferred();
			const s = await setup({}, (call) => call === 1 ? first.promise : second.promise);
			s.ctx.mode = "tui";
			await s.emit("agent_settled");
			await s.emit("agent_start");
			await s.emit("agent_before_settle", s.boundary());
			await s.emit("agent_settled");
			first.resolve(response("旧摘要"));
			await flush();
			assert.ok(s.calls[0].options.signal.aborted);
			assert.equal(s.calls[1].options.signal.aborted, false);
			second.resolve(response("新摘要"));
			await flush();
			assert.equal(packets.length, 1);
			assert.equal(packets[0].message, "新摘要");
		});
		await check("session switch, navigation and shutdown discard pending work", async () => {
			for (const event of ["session_before_switch", "session_before_fork", "session_before_tree", "session_shutdown", "session_start"]) {
				const pending = deferred();
				const s = await setup({}, () => pending.promise);
				s.ctx.mode = "tui";
				await s.emit("agent_settled");
				await s.emit(event);
				assert.ok(s.calls[0].options.signal.aborted);
				pending.resolve(response());
				await flush();
				assert.equal(packets.length, 0, event);
			}
		});
		await check("timeout falls back even when provider ignores abort", async () => {
			const pending = deferred();
			const s = await setup({ summary: { timeoutMs: 10 } }, () => pending.promise);
			await s.emit("agent_settled");
			assert.ok(s.calls[0].options.signal.aborted);
			assert.equal(packets[0].message, "✅ Pi 已完成，等待输入");
			pending.resolve(response("迟到摘要"));
			await flush();
			assert.equal(packets.length, 1);
		});
		await check("empty final reply and failed summary use fixed text", async () => {
			let s = await setup({ summary: { minInputChars: 0 } });
			await s.emit("agent_before_settle", s.boundary("completed", { ...assistant(), content: [] }));
			await s.emit("agent_settled");
			assert.equal(s.calls.length, 0);
			s = await setup({}, () => ({ ...response("不完整摘要"), stopReason: "error", errorMessage: "request failed" }));
			await s.emit("agent_settled");
			assert.equal(packets[0].message, "✅ Pi 已完成，等待输入");
		});
		await check("status preserves session overrides", async () => {
			const s = await setup();
			await s.command("plain");
			await s.command("status");
			await s.emit("agent_settled");
			assert.equal(s.calls.length, 0);
		});
		await check("a new session resets preferences and uses its own endpoint", async () => {
			const s = await setup();
			await s.command("off");
			s.writeConfig({ socket: "new-pet", title: "New session", summary: { enabled: false } });
			await s.emit("session_start");
			await s.emit("agent_start");
			await s.emit("agent_before_settle", s.boundary());
			await s.emit("agent_settled");
			assert.equal(packets.length, 1);
			assert.equal(packets[0].title, "New session");
			assert.ok(packets[0].endpoint.endsWith("new-pet"));
		});
		await check("native Pi provider keeps thinking on and disables it on request", async () => {
			const { stream } = await import(pathToFileURL(path.join(piAiDir, "api/openai-completions.js")));
			const { normalizeContext } = await import(pathToFileURL(path.join(piAiDir, "utils/transcript.js")));
			const model = { id: "test-qwen", name: "Test", api: "openai-completions", provider: "test", baseUrl: "http://127.0.0.1:1/v1", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 4096, compat: { thinkingFormat: "qwen-chat-template" } };
			for (const noThinking of [false, true]) {
				const s = await setup({ summary: { noThinking } });
				await s.emit("agent_settled");
				let payload;
				await stream(model, normalizeContext(s.calls[0].context), {
					...s.calls[0].options, apiKey: "mock",
					onPayload(next) { payload = next; throw new Error("Stop before network"); },
				}).result();
				assert.equal(payload.chat_template_kwargs.enable_thinking, !noThinking);
				assert.equal(payload.max_completion_tokens ?? payload.max_tokens, 512);
				if (noThinking) assert.equal(payload.reasoning_effort, "none");
			}
		});
		console.log(`${passed} Pi bell regression checks passed (no network or desktop notifications).`);
	}
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}
