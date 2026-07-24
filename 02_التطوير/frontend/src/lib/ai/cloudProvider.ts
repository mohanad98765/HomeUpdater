import { apiFetch } from "@/lib/utils";
import type { AIProvider, SolveRequest } from "./provider";

// ================================================================
// المزوّد السحابيّ = واجهة العميل المدفوعة الموجودة أصلًا (Anthropic عبر الـbackend).
// نتعامل معها كـ"واجهة خارجية" فقط: نستدعي نقطة النهاية القائمة، ولا نعدّل منطقها
// الداخليّ. تتطلّب مفتاح العميل (نفس مفتاح المستشار) وتعمل على أي جهاز به إنترنت.
// ================================================================

export const cloudProvider: AIProvider = {
  id: "cloud",

  async isAvailable() {
    try {
      const s = await apiFetch<{ configured: boolean }>("/api/advisor/support/status");
      return !!s.configured; // متاح فقط إن ضبط العميل مفتاحه
    } catch {
      return false;
    }
  },

  async solve({ question, context }: SolveRequest) {
    const content = context ? `${context}\n\n${question}` : question;
    const r = await apiFetch<{ reply: string }>("/api/advisor/support", {
      method: "POST",
      body: JSON.stringify({ messages: [{ role: "user", content }] }),
    });
    return r.reply;
  },
};
