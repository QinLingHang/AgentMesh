// Compatibility contract keywords: 个人大模型 Provider | API Key
import { useEffect, useMemo, useState } from "react";
import {
  createUserModelService,
  deleteUserModelService,
  friendlyApiError,
  listUserModelServices,
  updateUserModelService,
} from "../../api";
import type { UserModelService, UserModelServiceInput } from "../../types";
import { Icon } from "../../components/common/Icon";

type PresetId = "qwen" | "openai" | "custom";

type Preset = {
  label: string;
  description: string;
  values: Pick<UserModelServiceInput, "provider" | "baseUrl" | "modelName" | "visionModelName">;
};

const presets: Record<PresetId, Preset> = {
  qwen: {
    label: "通义千问",
    description: "使用 DashScope 官方兼容接口，适合 qwen-plus / qwen-vl-plus。",
    values: {
      provider: "qwen",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      modelName: "qwen-plus",
      visionModelName: "qwen-vl-plus",
    },
  },
  openai: {
    label: "OpenAI",
    description: "使用 OpenAI 官方 API 地址和模型。",
    values: {
      provider: "openai-compatible",
      baseUrl: "https://api.openai.com/v1",
      modelName: "gpt-4.1-mini",
      visionModelName: "gpt-4.1-mini",
    },
  },
  custom: {
    label: "自定义接口",
    description: "适用于 DeepSeek、OpenRouter、vLLM、自建网关等兼容 OpenAI API 的服务。",
    values: {
      provider: "openai-compatible",
      baseUrl: "",
      modelName: "",
      visionModelName: "",
    },
  },
};

function inferPreset(item: UserModelService | null): PresetId {
  if (!item) return "qwen";
  if (item.baseUrl.includes("dashscope.aliyuncs.com")) return "qwen";
  if (item.baseUrl.includes("api.openai.com")) return "openai";
  return "custom";
}

function defaultName(preset: PresetId) {
  if (preset === "qwen") return "我的通义千问";
  if (preset === "openai") return "我的 OpenAI";
  return "我的模型服务";
}

export function ModelSettings() {
  const [services, setServices] = useState<UserModelService[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [preset, setPreset] = useState<PresetId>("qwen");
  const [name, setName] = useState(defaultName("qwen"));
  const [provider, setProvider] = useState(presets.qwen.values.provider);
  const [baseUrl, setBaseUrl] = useState(presets.qwen.values.baseUrl);
  const [modelName, setModelName] = useState(presets.qwen.values.modelName);
  const [visionModelName, setVisionModelName] = useState(presets.qwen.values.visionModelName);
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [autoRoute, setAutoRoute] = useState(true);
  const [isDefault, setIsDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const editing = useMemo(
    () => services.find((item) => item.id === editingId) ?? null,
    [services, editingId],
  );

  const load = async () => {
    const items = await listUserModelServices();
    setServices(items);
    return items;
  };

  useEffect(() => {
    void load().catch((cause) => {
      setError(friendlyApiError(cause, "读取模型设置失败，请稍后重试。"));
    });
  }, []);

  const applyPreset = (next: PresetId, resetName = false) => {
    const value = presets[next];
    setPreset(next);
    setProvider(value.values.provider);
    setBaseUrl(value.values.baseUrl);
    setModelName(value.values.modelName);
    setVisionModelName(value.values.visionModelName);
    if (resetName) setName(defaultName(next));
  };

  const openCreate = (next: PresetId = "qwen") => {
    setEditingId(null);
    setShowEditor(true);
    setApiKey("");
    setEnabled(true);
    setAutoRoute(true);
    setIsDefault(services.length === 0);
    setName(defaultName(next));
    applyPreset(next, false);
    setError("");
    setNotice("");
  };

  const openEdit = (item: UserModelService) => {
    setEditingId(item.id);
    setShowEditor(true);
    setPreset(inferPreset(item));
    setName(item.name);
    setProvider(item.provider);
    setBaseUrl(item.baseUrl);
    setModelName(item.modelName);
    setVisionModelName(item.visionModelName);
    setApiKey("");
    setEnabled(item.enabled);
    setAutoRoute(item.autoRoute);
    setIsDefault(item.isDefault);
    setError("");
    setNotice("");
  };

  const closeEditor = () => {
    if (busy) return;
    setShowEditor(false);
    setEditingId(null);
    setApiKey("");
  };

  const choosePreset = (next: PresetId) => {
    applyPreset(next, editingId == null);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const input: UserModelServiceInput = {
        name: name.trim(),
        provider: provider.trim(),
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        visionModelName: visionModelName.trim(),
        apiKey: apiKey.trim(),
        enabled,
        autoRoute,
        isDefault,
      };

      if (editingId == null) {
        await createUserModelService(input);
        setNotice("模型服务已添加。它现在可以参与自动路由或被任务手动指定。");
      } else {
        await updateUserModelService(editingId, input);
        setNotice("模型服务已更新。接口密钥留空时会继续使用原密钥。");
      }
      await load();
      setShowEditor(false);
      setEditingId(null);
      setApiKey("");
    } catch (cause) {
      setError(friendlyApiError(cause, "保存模型服务失败，请检查接口地址、模型名称和密钥。"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: UserModelService) => {
    if (!window.confirm(`删除模型服务「${item.name}」？删除后该服务将不能再被任务选择。`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteUserModelService(item.id);
      await load();
      if (editingId === item.id) closeEditor();
      setNotice(`模型服务「${item.name}」已删除。`);
    } catch (cause) {
      setError(friendlyApiError(cause, "删除模型服务失败，请稍后重试。"));
    } finally {
      setBusy(false);
    }
  };

  const enabledCount = services.filter((item) => item.enabled).length;
  const autoCount = services.filter((item) => item.enabled && item.autoRoute).length;

  return (
    <section className="page calm-page model-settings-page" data-testid="model-settings-page">
      <header className="calm-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">个人设置</span>
          <h1>模型设置</h1>
          <p>保存多个自己的模型服务。默认由 AgentMesh 自动选择，也可以在工作台为当前任务手动指定。</p>
        </div>
        <span className={`model-provider-state ${enabledCount > 0 ? "ready" : "empty"}`}>
          <span />
          {enabledCount > 0 ? `${enabledCount} 个服务可用 · ${autoCount} 个参与自动路由` : "尚未配置"}
        </span>
      </header>

      {error && <div className="calm-feedback error">{error}</div>}
      {notice && <div className="calm-feedback success">{notice}</div>}

      <section className="model-pool-card">
        <div className="model-pool-head">
          <div>
            <span className="model-settings-icon"><Icon name="server" size={18} /></span>
            <div>
              <h2>我的模型服务</h2>
              <p>每个服务拥有独立 API Key。密钥只加密保存在你的账号下，浏览器只会看到脱敏提示。</p>
            </div>
          </div>
          <button className="calm-button primary" type="button" onClick={() => openCreate()}>
            + 添加模型服务
          </button>
        </div>

        {services.length === 0 ? (
          <div className="model-pool-empty">
            <Icon name="server" size={22} />
            <strong>还没有模型服务</strong>
            <span>添加通义千问、OpenAI 或任意兼容 OpenAI API 的模型服务后即可运行任务。</span>
            <button className="calm-button primary" type="button" onClick={() => openCreate()}>添加第一个模型服务</button>
          </div>
        ) : (
          <div className="model-service-list">
            {services.map((item) => (
              <article className={`model-service-card ${item.enabled ? "enabled" : "disabled"}`} key={item.id}>
                <div className="model-service-main">
                  <span className="model-service-mark"><Icon name="server" size={16} /></span>
                  <div>
                    <div className="model-service-title">
                      <strong>{item.name}</strong>
                      {item.isDefault && <span className="model-service-tag">默认</span>}
                      {item.autoRoute && item.enabled && <span className="model-service-tag route">自动路由</span>}
                    </div>
                    <p>{item.modelName}{item.visionModelName ? ` · 视觉 ${item.visionModelName}` : ""}</p>
                    <small>{item.provider} · {item.maskedHint}</small>
                  </div>
                </div>
                <span className={`calm-status ${item.enabled ? "ok" : ""}`}><i />{item.enabled ? "已启用" : "已停用"}</span>
                <div className="model-service-actions">
                  <button className="calm-button" type="button" onClick={() => openEdit(item)}>编辑</button>
                  <button className="calm-button danger-soft" type="button" disabled={busy} onClick={() => void remove(item)}>删除</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {showEditor && (
        <section className="model-settings-card model-service-editor" data-testid="model-service-editor">
          <div className="model-settings-card-head">
            <span className="model-settings-icon"><Icon name="server" size={18} /></span>
            <div>
              <h2>{editing ? `编辑「${editing.name}」` : "添加模型服务"}</h2>
              <p>{presets[preset].description}</p>
            </div>
          </div>

          <div className="model-preset-row" role="group" aria-label="模型服务预设">
            {(Object.entries(presets) as [PresetId, Preset][]).map(([id, item]) => (
              <button key={id} type="button" className={preset === id ? "active" : ""} onClick={() => choosePreset(id)}>
                {item.label}
              </button>
            ))}
          </div>

          <div className="model-settings-grid">
            <label>
              <span>配置名称</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：我的 DeepSeek" />
            </label>
            <label>
              <span>服务类型</span>
              <input value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="openai-compatible" />
            </label>
            <label className="model-wide-field">
              <span>接口地址</span>
              <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="例如：https://api.deepseek.com/v1" />
            </label>
            <label>
              <span>文本模型</span>
              <input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="例如：deepseek-chat" />
            </label>
            <label>
              <span>视觉模型（可选）</span>
              <input value={visionModelName} onChange={(event) => setVisionModelName(event.target.value)} placeholder="留空表示该服务不参与图片任务" />
            </label>
            <label className="model-api-key-field">
              <span>接口密钥</span>
              <input
                type="password"
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={editing ? `已保存 ${editing.maskedHint}；留空表示保持不变` : "请输入你自己的 API Key"}
                data-testid="user-model-api-key"
              />
            </label>
          </div>

          <div className="model-service-toggles">
            <label className="model-enabled-row">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => {
                  setEnabled(event.target.checked);
                  if (!event.target.checked) setIsDefault(false);
                }}
              />
              <span>启用这个模型服务</span>
            </label>
            <label className="model-enabled-row">
              <input type="checkbox" checked={autoRoute} onChange={(event) => setAutoRoute(event.target.checked)} />
              <span>加入自动路由</span>
            </label>
            <label className="model-enabled-row">
              <input
                type="checkbox"
                checked={isDefault}
                disabled={!enabled}
                onChange={(event) => setIsDefault(event.target.checked)}
              />
              <span>设为默认服务</span>
            </label>
          </div>

          <div className="model-security-note">
            <Icon name="shield" size={17} />
            <div>
              <strong>密钥始终属于当前账号</strong>
              <span>后端使用 AES-GCM 加密保存。自动路由只接收请求级候选服务，明文密钥不会返回浏览器，也不会写入任务记录。</span>
            </div>
          </div>

          <div className="model-settings-actions">
            <button className="calm-button subtle" type="button" disabled={busy} onClick={closeEditor}>取消</button>
            <button
              className="calm-button primary"
              type="button"
              disabled={busy || !name.trim() || !provider.trim() || !baseUrl.trim() || !modelName.trim() || (!editing && !apiKey.trim())}
              onClick={() => void save()}
              data-testid="user-model-save"
            >
              {busy ? "正在保存…" : editing ? "保存修改" : "添加模型服务"}
            </button>
          </div>
        </section>
      )}

      <section className="model-usage-policy">
        <h2>调用规则</h2>
        <div className="model-policy-grid">
          <div><strong>自动选择</strong><span>默认从已启用且加入自动路由的个人模型中，根据质量、成本、延迟和历史成功率选择。</span></div>
          <div><strong>手动指定</strong><span>工作台可以为本次任务指定某个模型服务。显式选择优先，但仍必须通过 BYOK、权限和可用性检查。</span></div>
          <div><strong>共享项目</strong><span>有个人模型池时仍优先使用个人模型；没有个人配置时，才允许回退到项目管理员显式配置的项目模型。</span></div>
        </div>
      </section>
    </section>
  );
}
