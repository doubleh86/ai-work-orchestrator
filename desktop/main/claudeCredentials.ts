import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { ClaudeCredentialStatus } from "../shared/claudeCredentials";

interface CredentialEncryption {
  isEncryptionAvailable(): boolean;
  encryptString(value: string): Buffer;
  decryptString(value: Buffer): string;
  getSelectedStorageBackend(): string;
}
const validKey = (value: unknown): value is string => typeof value === "string" && Boolean(value.trim())
  && value.length <= 4096 && !/[\x00-\x20\x7f-\uffff]/u.test(value.trim()) && !/[\0\r\n]/u.test(value);
const missingFile = (error: unknown): boolean => Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");

/** Owns the app key; public status never contains credential material. */
export class ClaudeCredentialStore {
  private key: string | undefined;
  private stored = false;
  private error = "";

  constructor(private readonly filePath: string, private readonly encryption: CredentialEncryption,
    private readonly environmentConfigured: () => boolean) {
    try {
      const encrypted = readFileSync(filePath);
      this.stored = true;
      if (!this.storageAvailable()) throw Error("unavailable");
      const key = this.encryption.decryptString(encrypted);
      if (!validKey(key)) throw Error("invalid credential");
      this.key = key.trim();
    } catch (error) {
      if (this.stored || !missingFile(error)) {
        this.stored = true;
        this.error = "저장된 Claude 키를 열지 못했습니다. 키를 다시 저장하거나 삭제해 주세요.";
      }
    }
  }

  apiKey(): string | undefined { return this.key; }

  status(): ClaudeCredentialStatus {
    return { source: this.key ? "app" : this.environmentConfigured() ? "environment" : "none",
      hasStoredKey: this.stored, storageAvailable: this.storageAvailable(), error: this.error };
  }

  save(value: unknown): ClaudeCredentialStatus {
    if (!validKey(value)) return this.fail("Claude API 키를 한 줄로 입력해 주세요.");
    if (!this.storageAvailable()) return this.fail("OS 보안 저장소를 사용할 수 없어 키를 저장하지 않았습니다.");
    const temporaryPath = `${this.filePath}.${randomUUID()}.tmp`;
    try {
      const encrypted = this.encryption.encryptString(value.trim());
      mkdirSync(dirname(this.filePath), { recursive: true, mode: 0o700 });
      writeFileSync(temporaryPath, encrypted, { flag: "wx", mode: 0o600 });
      renameSync(temporaryPath, this.filePath);
      this.key = value.trim(); this.stored = true; this.error = "";
    } catch {
      this.error = "Claude 키를 저장하지 못했습니다. 기존 설정은 유지됩니다. 다시 시도해 주세요.";
    } finally {
      try { unlinkSync(temporaryPath); } catch { /* A failed atomic write may not create a temporary file. */ }
    }
    return this.status();
  }

  delete(): ClaudeCredentialStatus {
    try {
      try { unlinkSync(this.filePath); } catch (error) { if (!missingFile(error)) throw error; }
      this.key = undefined; this.stored = false; this.error = "";
    } catch { this.error = "Claude 키를 삭제하지 못했습니다. 다시 시도해 주세요."; }
    return this.status();
  }

  private fail(message: string): ClaudeCredentialStatus { this.error = message; return this.status(); }

  private storageAvailable(): boolean {
    try {
      return this.encryption.isEncryptionAvailable()
        && (process.platform !== "linux" || this.encryption.getSelectedStorageBackend() !== "basic_text");
    } catch { return false; }
  }
}
