import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import type { NvidiaCredentialStatus } from "../shared/nvidiaCredentials";

interface CredentialEncryption {
  isEncryptionAvailable(): boolean;
  encryptString(value: string): Buffer;
  decryptString(value: Buffer): string;
  getSelectedStorageBackend(): string;
}
interface CredentialVault {
  version: 1;
  keys: Array<{ id: string; label: string; value: string }>;
  defaultKeyId: string;
  modelBindings: Record<string, string>;
}
const emptyVault = (): CredentialVault => ({ version: 1, keys: [], defaultKeyId: "", modelBindings: {} });
const validKey = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0
  && value.length <= 4096 && !/[\x00-\x1f\x7f]/.test(value);
const validLabel = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0
  && value.length <= 80 && !/[\x00-\x1f\x7f]/.test(value);
const validId = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9-]{1,64}$/.test(value);
const validModel = (value: string): boolean => value.length <= 200 && /^[A-Za-z0-9._-]+\/[A-Za-z0-9._/-]+$/.test(value);
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const missingFile = (error: unknown): boolean => isObject(error) && error.code === "ENOENT";

function routing(vault: CredentialVault, defaultKeyId: unknown, bindings: unknown): CredentialVault {
  if (typeof defaultKeyId !== "string" || !isObject(bindings) || Object.keys(bindings).length > 128
    || (vault.keys.length ? !vault.keys.some(key => key.id === defaultKeyId) : defaultKeyId !== "")) throw Error("invalid routing");
  const modelBindings: Record<string, string> = {};
  for (const [model, id] of Object.entries(bindings)) {
    if (!validModel(model) || typeof id !== "string" || !vault.keys.length
      || (id !== "" && !vault.keys.some(key => key.id === id))) throw Error("invalid routing");
    modelBindings[model] = id;
  }
  return { ...vault, defaultKeyId, modelBindings };
}

function parseVault(plaintext: string): CredentialVault {
  if (!plaintext.startsWith("{")) {
    if (!validKey(plaintext)) throw Error("invalid credential");
    return { version: 1, keys: [{ id: "default", label: "기본 키", value: plaintext.trim() }], defaultKeyId: "default", modelBindings: {} };
  }
  const raw: unknown = JSON.parse(plaintext);
  if (!isObject(raw) || raw.version !== 1 || !Array.isArray(raw.keys) || raw.keys.length > 64) throw Error("invalid vault");
  const keys: CredentialVault["keys"] = [];
  for (const key of raw.keys) {
    if (!isObject(key) || !validId(key.id) || !validLabel(key.label) || !validKey(key.value)) throw Error("invalid credential");
    const { id, label, value } = key;
    if (keys.some(existing => existing.id === id || existing.label === label.trim())) throw Error("invalid credential");
    keys.push({ id, label: label.trim(), value: value.trim() });
  }
  return routing({ ...emptyVault(), keys }, raw.defaultKeyId, raw.modelBindings);
}

/** Owns encrypted app credentials. Public status contains names and IDs only. */
export class NvidiaCredentialStore {
  private vault = emptyVault();
  private stored = false;
  private error = "";

  constructor(private readonly filePath: string, private readonly encryption: CredentialEncryption,
    private readonly environmentConfigured: () => boolean) {
    try {
      const encrypted = readFileSync(filePath);
      this.stored = true;
      if (!this.storageAvailable()) throw Error("unavailable");
      this.vault = parseVault(encryption.decryptString(encrypted));
    } catch (error) {
      if (this.stored || !missingFile(error)) {
        this.stored = true;
        this.error = "저장된 NVIDIA 키를 열지 못했습니다. 키를 다시 저장하거나 삭제해 주세요.";
      }
    }
  }

  apiKey(): string | undefined {
    return this.vault.keys.find(key => key.id === this.vault.defaultKeyId)?.value;
  }

  modelApiKeys(): Record<string, string> {
    return Object.fromEntries(Object.entries(this.vault.modelBindings).map(([model, id]) => {
      const key = this.vault.keys.find(key => key.id === (id || this.vault.defaultKeyId));
      if (!key) throw Error("Invalid NVIDIA credential binding");
      return [model, key.value];
    }));
  }

  status(): NvidiaCredentialStatus {
    const source = this.apiKey() ? "app" : this.environmentConfigured() ? "environment" : "none";
    return { configured: source !== "none", source, hasStoredKey: this.stored, storageAvailable: this.storageAvailable(), error: this.error,
      keys: this.vault.keys.map(({ id, label }) => ({ id, label })), defaultKeyId: this.vault.defaultKeyId,
      modelBindings: { ...this.vault.modelBindings } };
  }

  save(value: unknown, options?: unknown): NvidiaCredentialStatus {
    if (!validKey(value)) return this.fail("NVIDIA API 키를 한 줄로 입력해 주세요.");
    let id = options === undefined ? this.vault.defaultKeyId : "";
    let label = this.vault.keys.find(key => key.id === id)?.label || "기본 키";
    if (options !== undefined) {
      if (!isObject(options) || !validLabel(options.label)
        || (options.id !== undefined && (!validId(options.id) || !this.vault.keys.some(key => key.id === options.id)))) {
        return this.fail("키 이름과 교체할 키를 확인해 주세요.");
      }
      label = options.label.trim();
      id = typeof options.id === "string" ? options.id : "";
    }
    if (this.vault.keys.some(key => key.label === label && key.id !== id)) return this.fail("다른 이름으로 키를 등록해 주세요.");
    if (!id && this.vault.keys.length >= 64) return this.fail("저장 가능한 키 수를 초과했습니다.");
    id ||= randomUUID();
    const keys = this.vault.keys.filter(key => key.id !== id);
    keys.push({ id, label, value: value.trim() });
    return this.commit({ ...this.vault, keys, defaultKeyId: this.vault.defaultKeyId || id });
  }

  delete(requestedId?: unknown): NvidiaCredentialStatus {
    const id = requestedId === undefined ? this.vault.defaultKeyId : requestedId;
    if (typeof id !== "string" || (id && !this.vault.keys.some(key => key.id === id))) return this.fail("삭제할 키를 확인해 주세요.");
    if (this.vault.keys.length === 1 && Object.keys(this.vault.modelBindings).length) {
      return this.fail("모델별 키 설정을 먼저 삭제한 뒤 마지막 키를 삭제해 주세요.");
    }
    if (Object.values(this.vault.modelBindings).includes(id)) return this.fail("이 키를 사용하는 모델의 키 연결을 먼저 변경하거나 해제해 주세요.");
    if (id === this.vault.defaultKeyId && this.vault.keys.length > 1) return this.fail("기본 키를 다른 키로 선택한 뒤 삭제해 주세요.");
    const keys = this.vault.keys.filter(key => key.id !== id);
    return this.commit({ ...this.vault, keys, defaultKeyId: keys.length ? this.vault.defaultKeyId : "" });
  }

  setRouting(defaultKeyId: unknown, bindings: unknown): NvidiaCredentialStatus {
    try { return this.commit(routing(this.vault, defaultKeyId, bindings)); }
    catch { return this.fail("기본 키와 모델별 키 연결을 확인해 주세요."); }
  }

  private fail(message: string): NvidiaCredentialStatus {
    this.error = message;
    return this.status();
  }

  private commit(vault: CredentialVault): NvidiaCredentialStatus {
    if (vault.keys.length && !this.storageAvailable()) return this.fail("OS 보안 저장소를 사용할 수 없어 키를 저장하지 않았습니다.");
    const temporaryPath = `${this.filePath}.${randomUUID()}.tmp`;
    try {
      if (vault.keys.length) {
        const encrypted = this.encryption.encryptString(JSON.stringify(vault));
        mkdirSync(dirname(this.filePath), { recursive: true, mode: 0o700 });
        writeFileSync(temporaryPath, encrypted, { flag: "wx", mode: 0o600 });
        renameSync(temporaryPath, this.filePath);
      } else {
        try { unlinkSync(this.filePath); } catch (error) { if (!missingFile(error)) throw error; }
      }
      this.vault = vault;
      this.stored = vault.keys.length > 0;
      this.error = "";
    } catch {
      this.error = "NVIDIA 키 설정을 저장하지 못했습니다. 기존 설정은 유지됩니다. 다시 시도해 주세요.";
    } finally {
      try { unlinkSync(temporaryPath); } catch { /* A failed atomic write may not create a temporary file. */ }
    }
    return this.status();
  }

  private storageAvailable(): boolean {
    try {
      return this.encryption.isEncryptionAvailable()
        && (process.platform !== "linux" || this.encryption.getSelectedStorageBackend() !== "basic_text");
    } catch { return false; }
  }
}
