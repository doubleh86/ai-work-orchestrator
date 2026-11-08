import { useRef, useState } from "react";
import { Gauge } from "lucide-react";

import { WorkDialog } from "./WorkDialog";

type Provider = "codex" | "claude";
type QuotaWindow = { used_percent: number; resets_at: number | null; reset_label: string };
type AccountUsage = {
  status: "available" | "unavailable" | "signed_out" | "api_key" | "not_installed" | "error";
  five_hour: QuotaWindow | null;
  weekly: QuotaWindow | null;
};

const providers = [{ id: "codex", label: "Codex" }, { id: "claude", label: "Claude" }] as const;
const messages: Record<Exclude<AccountUsage["status"], "available">, string> = {
  unavailable: "공급자가 이 계정의 한도 사용률을 제공하지 않았습니다.",
  signed_out: "구독 계정으로 로그인해 주세요.",
  api_key: "API 키로 연결됨 · 구독 한도 적용 대상 아님",
  not_installed: "CLI를 설치한 뒤 다시 확인해 주세요.",
  error: "사용량을 확인하지 못했습니다. 다시 확인해 주세요.",
};
const failedUsage: AccountUsage = { status: "error", five_hour: null, weekly: null };

function Quota({ label, value }: { label: string; value: QuotaWindow | null }) {
  if (!value) return <div className="account-usage__quota"><strong>{label}</strong><span>미제공</span></div>;
  const resetDate = value.resets_at === null ? null : new Date(value.resets_at * 1000);
  return <div className="account-usage__quota">
    <strong>{label}</strong><span>{value.used_percent.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}% 사용</span>
    <meter aria-label={`${label} 한도 사용률`} min={0} max={100} value={value.used_percent} />
    <small>리셋 {resetDate ? <time dateTime={resetDate.toISOString()}>
      {resetDate.toLocaleString("ko-KR", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
    </time> : value.reset_label || "시각 미제공"}</small>
  </div>;
}

export function AccountUsageControl() {
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState<Partial<Record<Provider, AccountUsage>>>({});
  const checking = useRef(false);

  async function refresh() {
    if (checking.current) return;
    checking.current = true;
    setUsage({});
    try {
      await Promise.all(providers.map(async ({ id }) => {
        let result: AccountUsage;
        try { result = await window.orchestrator.request<AccountUsage>("providers.accountUsage", { provider: id }); }
        catch { result = failedUsage; }
        setUsage((current) => ({ ...current, [id]: result }));
      }));
    } finally {
      checking.current = false;
    }
  }

  return <>
    <button className="button button--quiet account-usage__trigger" type="button" aria-haspopup="dialog"
      aria-label="AI 사용량" aria-expanded={open} onClick={() => { setOpen(true); void refresh(); }}>
      <Gauge size={16} aria-hidden="true" /><span>AI 사용량</span>
    </button>
    {open ? <WorkDialog portal title="AI 계정 사용량" onClose={() => setOpen(false)}
      footer={<button type="button" className="button button--secondary" disabled={providers.some(({ id }) => !usage[id])}
        onClick={() => void refresh()}>새로 확인</button>}>
      <div className="account-usage__providers">
        {providers.map(({ id, label }) => {
          const result = usage[id];
          return <section className="account-usage__provider" key={id} aria-label={label}>
            <h3>{label}</h3>
            {!result ? <p role="status">확인 중…</p> : result.status === "available" ? <>
              <Quota label="5시간" value={result.five_hour} />
              <Quota label="주간" value={result.weekly} />
            </> : <p role={result.status === "error" ? "alert" : undefined}>{messages[result.status]}</p>}
          </section>;
        })}
      </div>
    </WorkDialog> : null}
  </>;
}
