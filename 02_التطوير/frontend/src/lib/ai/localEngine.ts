import type { AIProvider, SolveRequest } from "./provider";

// ================================================================
// المحرّك المجانيّ المدمج: نموذج لغويّ صغير (~0.5–1B) يعمل داخل نافذة WebView2
// عبر WebGPU (مكتبة @mlc-ai/web-llm). بلا مفتاح، وبلا خادم خارجيّ للذكاء.
//
// قرارات مهمّة للتوزيع على أجهزة كثيرة متنوّعة:
//  • الاستيراد كسول (dynamic import) → لا تُحمَّل المكتبة الثقيلة إلا عند اختيار
//    المحليّ فعلًا، فلا تُثقل حزمة الأجهزة التي لا تستخدمه.
//  • كشف WebGPU أولًا → على جهازٍ بلا WebGPU يكون المحليّ "غير متاح" (يسقط للسحابيّ).
//  • النموذج يُنزَّل مرّة واحدة ويُخزَّن في ذاكرة المتصفح (Cache/OPFS) → التشغيلات
//    التالية بلا إنترنت. المثبِّت يبقى صغيرًا (النموذج غير مُحزَّم).
// ================================================================

// نُفضّل الأصغر أولًا؛ ونختار المعرّف من قائمة النماذج الجاهزة وقت التشغيل حتى لا
// ينكسر لو تغيّرت الأسماء في إصدارٍ لاحق من المكتبة.
const PREFERRED = [
  "Qwen2.5-0.5B-Instruct-q4f16_1-MLC",
  "Llama-3.2-1B-Instruct-q4f16_1-MLC",
  "Phi-3.5-mini-instruct-q4f16_1-MLC",
];

const SYSTEM =
  "أنت مساعد أمن شبكات منزليّة. اشرح خطورة الثغرات المعطاة بإيجاز، ثم قدّم خطوات " +
  "معالجة عمليّة وواضحة. أجب بلغة المستخدم، وبدون حشو.";

// كائن المحرّك يُحمَّل مرّة واحدة فقط (Singleton) — للأداء ولعزل الموارد.
let enginePromise: Promise<MLCEngineLike> | null = null;

interface MLCEngineLike {
  chat: { completions: { create: (o: unknown) => Promise<AsyncIterable<StreamPart>> } };
  unload?: () => Promise<void>;
}
interface StreamPart {
  choices?: { delta?: { content?: string } }[];
}

/** كشف قدرة WebGPU — بدونها لا يمكن تشغيل المحرّك المحليّ إطلاقًا. */
export function localSupported(): boolean {
  return typeof navigator !== "undefined" && "gpu" in navigator;
}

async function getEngine(onProgress?: SolveRequest["onProgress"]): Promise<MLCEngineLike> {
  if (enginePromise) return enginePromise;
  enginePromise = (async () => {
    // استيراد كسول للمكتبة الثقيلة — يُنتِج chunk منفصلًا لا يُحمَّل إلا هنا.
    const webllm = await import("@mlc-ai/web-llm");
    const ids: string[] = webllm.prebuiltAppConfig.model_list.map(
      (m: { model_id: string }) => m.model_id,
    );
    const modelId = PREFERRED.find((m) => ids.includes(m)) ?? ids[0];
    return webllm.CreateMLCEngine(modelId, {
      initProgressCallback: (r: { progress?: number; text?: string }) =>
        onProgress?.(r.progress ?? 0, r.text ?? ""),
    }) as unknown as MLCEngineLike;
  })();
  return enginePromise;
}

export const localProvider: AIProvider = {
  id: "local",

  async isAvailable() {
    return localSupported();
  },

  async solve({ question, context, onToken, onProgress, signal }: SolveRequest) {
    const engine = await getEngine(onProgress);
    const messages = [
      { role: "system", content: SYSTEM },
      { role: "user", content: context ? `${context}\n\nالسؤال: ${question}` : question },
    ];
    // بثّ تدريجيّ: تظهر أوّل الكلمات فورًا فيبدو الردّ آنيًّا كالسحابيّ.
    const stream = await engine.chat.completions.create({ messages, stream: true });
    let full = "";
    for await (const part of stream) {
      if (signal?.aborted) break;
      const delta = part.choices?.[0]?.delta?.content ?? "";
      if (delta) {
        full += delta;
        onToken?.(delta);
      }
    }
    return full.trim();
  },

  async dispose() {
    // تحرير ذاكرة GPU عند التبديل للسحابيّ — يمنع تداخل موارد المحرّكَين.
    const e = enginePromise ? await enginePromise : null;
    await e?.unload?.();
    enginePromise = null;
  },
};
