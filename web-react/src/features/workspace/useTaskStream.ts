/**
 * Reserved for a future server-sent token stream.
 *
 * The current production Go/Python contract returns RunResult and durable tasks
 * are observed through persisted task/message polling in Workspace.tsx.  We do
 * not fake a network token stream here: the workspace gives immediate execution
 * feedback while the task is running, then progressively reveals the persisted
 * final answer.
 *
 * When the backend exposes a stable SSE/NDJSON endpoint, implement that transport
 * here and keep MessageHistory as the presentation layer.
 */
export {};
