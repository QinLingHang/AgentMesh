// Compatibility contract keywords: 个人大模型 Provider | API Key
import { useEffect, useState } from "react";
import {
  deleteUserModelProvider,
  friendlyApiError,
  getUserModelProvider,
  upsertUserModelProvider,
} from "../../api";
import type { UserModelProvider, UserModelProviderInput } from "../../types";
import { Icon } from "../../components/common/Icon";

type PresetId = "qwen" | "openai" | "custom";

const presets: Record<Exclude<PresetId, "custom">, Omit<UserModelProviderInput, "apiKey" | "enabled">> = {
  qwen: {
    provider: "qwen",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    modelName: "qwen-plus",
    visionModelName: "qwen-vl-plus",
  },
  openai: {
    provider: "openai-compatible",
    baseUrl: "https://api.openai.com/v1",
    modelName: "gpt-4.1-mini",
    visionModelName: "gpt-4.1-mini",
  },
};

function inferPreset(item: UserModelProvider | null): PresetId {
  if (!item) return "qwen";
  if (item.baseUrl.includes("dashscope.aliyuncs.com")) return "qwen";
  if (item.baseUrl.includes("api.openai.com")) return "openai";
  return "custom";
}

export function ModelSettings() {
  const [saved, setSaved] = useState<UserModelProvider | null>(null);
  const [preset, setPreset] = useState<PresetId>("qwen");
  const [provider, setProvider] = useState(presets.qwen.provider);
  const [baseUrl, setBaseUrl] = useState(presets.qwen.baseUrl);
  const [modelName, setModelName] = useState(presets.qwen.modelName);
  const [visionModelName, setVisionModelName] = useState(presets.qwen.visionModelName);
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applySaved = (item: UserModelProvider | null) => {
    setSaved(item);
    const detected = inferPreset(item);
    setPreset(detected);
    if (item) {
      setProvider(item.provider);
      setBaseUrl(item.baseUrl);
      setModelName(item.modelName);
      setVisionModelName(item.visionModelName);
      setEnabled(item.enabled);
    } else {
      const defaults = presets.qwen;
      setProvider(defaults.provider);
      setBaseUrl(defaults.baseUrl);
      setModelName(defaults.modelName);
      setVisionModelName(defaults.visionModelName);
      setEnabled(true);
    }
    setApiKey("");
  };

  useEffect(() => {
    void (async () => {
      try {
        applySaved(await getUserModelProvider());
      } catch (e) {
        setError(friendlyApiError(e, "读取模型设置失败，请稍后重试。"));
      }
    })();
  }, []);

  const choosePreset = (next: PresetId) => {
    setPreset(next);
    if (next === "custom") return;
    const value = presets[next];
    setProvider(value.provider);
    setBaseUrl(value.baseUrl);
    setModelName(value.modelName);
    setVisionModelName(value.visionModelName);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const item = await upsertUserModelProvider({
        provider: provider.trim(),
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        visionModelName: visionModelName.trim(),
        apiKey: apiKey.trim(),
        enabled,
      });
      applySaved(item);
      setNotice("模型配置已保存。之后的个人会话会使用你自己的 接口密钥。");
    } catch (e) {
      setError(friendlyApiError(e, "保存模型配置失败，请检查接口地址和参数。"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!saved || !window.confirm("删除个人模型配置？删除后个人工作区将无法调用大模型，直到重新配置。")) {
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteUserModelProvider();
      applySaved(null);
      setNotice("个人模型配置已删除。");
    } catch (e) {
      setError(friendlyApiError(e, "删除模型配置失败，请稍后重试。"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page calm-page model-settings-page" data-testid="model-settings-page">
      <header className="calm-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">个人设置</span>
          <h1>模型设置</h1>
          <p>连接你自己的大模型账号。AgentMesh 不会把 接口密钥 明文返回到浏览器。</p>
        </div>
        <span className={`model-provider-state ${saved?.enabled ? "ready" : "empty"}`}>
          <span />
          {saved?.enabled ? `已配置 · ${saved.maskedHint}` : "尚未配置"}
        </span>
      </header>

      <section className="model-settings-card">
        <div className="model-settings-card-head">
          <span className="model-settings-icon"><Icon name="server" size={18} /></span>
          <div>
            <h2>个人大模型服务</h2>
            <p>普通聊天优先使用你的个人配置；共享项目只有在你没有个人配置时，才会使用项目管理员明确配置的 项目自带模型密钥。</p>
          </div>
        </div>

        <div className="model-preset-row" role="group" aria-label="模型服务预设">
          {([
            ["qwen", "通义千问"],
            ["openai", "OpenAI"],
            ["custom", "兼容 OpenAI 接口"],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={preset === id ? "active" : ""}
              onClick={() => choosePreset(id)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="model-settings-grid">
          <label>
            <span>服务类型</span>
            <input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="openai-compatible" />
          </label>
          <label>
            <span>接口地址</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://.../v1" />
          </label>
          <label>
            <span>文本模型</span>
            <input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="qwen-plus" />
          </label>
          <label>
            <span>视觉模型（可选）</span>
            <input value={visionModelName} onChange={(e) => setVisionModelName(e.target.value)} placeholder="qwen-vl-plus；留空则不启用视觉知识解析" />
          </label>
          <label className="model-api-key-field">
            <span>接口密钥</span>
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={saved ? `已保存 ${saved.maskedHint}；留空表示保持不变` : "请输入你自己的 接口密钥"}
              data-testid="user-model-api-key"
            />
          </label>
        </div>

        <label className="model-enabled-row">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>启用这套个人模型配置</span>
        </label>

        <div className="model-security-note">
          <Icon name="shield" size={17} />
          <div>
            <strong>你的密钥只属于当前账号</strong>
            <span>后端使用 AES-GCM 加密算法 加密保存，并以 用户账号 作为加密上下文。明文只在当前请求转发到受信任的 运行服务 时短暂存在。</span>
          </div>
        </div>

        {error && <div className="calm-feedback error">{error}</div>}
        {notice && <div className="calm-feedback success">{notice}</div>}

        <div className="model-settings-actions">
          {saved && (
            <button className="calm-button subtle" type="button" disabled={busy} onClick={() => void remove()}>
              删除个人配置
            </button>
          )}
          <button
            className="calm-button primary"
            type="button"
            disabled={busy || !provider.trim() || !baseUrl.trim() || !modelName.trim() || (!saved && !apiKey.trim())}
            onClick={() => void save()}
            data-testid="user-model-save"
          >
            {busy ? "正在保存…" : "保存模型配置"}
          </button>
        </div>
      </section>

      <section className="model-usage-policy">
        <h2>调用规则</h2>
        <div className="model-policy-grid">
          <div><strong>个人工作区</strong><span>必须使用当前登录用户自己的模型配置，不再回退到平台维护者的 接口密钥。</span></div>
          <div><strong>共享项目</strong><span>优先使用成员自己的模型配置；没有个人配置时，才允许使用项目管理员显式配置的 项目自带模型密钥。</span></div>
          <div><strong>没有任何配置</strong><span>请求会直接提示“请先配置模型”，不会偷偷消费平台模型额度。</span></div>
        </div>
      </section>
    </section>
  );
}
