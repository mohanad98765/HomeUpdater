import { localProvider, localSupported } from "./localEngine";
import { cloudProvider } from "./cloudProvider";
import type { ProviderId, SolveRequest } from "./provider";

// ================================================================
// دالّة التبديل (جوهر النظام): تختار المزوّد حسب رغبة المستخدم، وتعزل مسار كلٍّ
// منهما تمامًا، وتسقط تلقائيًّا للسحابيّ إذا فشل المحليّ (WebGPU غائب، أو النموذج
// أكبر من ذاكرة الجهاز، أو خطأ تشغيل). لا تنهار أبدًا بصمت — إمّا نتيجة أو رسالة.
// ================================================================

export interface SolveResult {
  providerUsed: ProviderId;
  answer: string;
  /** هل اضطُررنا للسقوط من المحليّ إلى السحابيّ؟ (لإبلاغ المستخدم بشفافية). */
  fellBack: boolean;
}

export async function solveProblem(chosen: ProviderId, req: SolveRequest): Promise<SolveResult> {
  // ---- المسار المحليّ: بلا أي طلب HTTP خارجيّ لذكاء اصطناعيّ (عزلٌ تامّ) ----
  if (chosen === "local") {
    if (!localSupported()) {
      // كشفٌ مبكر: لا WebGPU → لا تُهدر وقتًا في تحميل نموذج لن يعمل.
      return fallbackToCloud(req, "WebGPU غير مدعوم على هذا الجهاز");
    }
    try {
      const answer = await localProvider.solve(req);
      return { providerUsed: "local", answer, fellBack: false };
    } catch (err) {
      // فشل تشغيل المحليّ (غالبًا نفاد ذاكرة GPU / نموذج كبير) → محاولة السحابيّ.
      return fallbackToCloud(req, err instanceof Error ? err.message : String(err));
    }
  }

  // ---- المسار المدفوع: توجيه مباشر لواجهة العميل، بلا تحميل أي نموذج محليّ ----
  const answer = await cloudProvider.solve(req);
  return { providerUsed: "cloud", answer, fellBack: false };
}

async function fallbackToCloud(req: SolveRequest, reason: string): Promise<SolveResult> {
  if (await cloudProvider.isAvailable()) {
    const answer = await cloudProvider.solve(req);
    return { providerUsed: "cloud", answer, fellBack: true };
  }
  // لا محليّ ولا سحابيّ مُفعَّل → رسالة واضحة بدل انهيارٍ صامت.
  throw new Error(
    `تعذّر تشغيل المحرّك المحليّ (${reason})، ولا يوجد مزوّد سحابيّ مُفعَّل. ` +
      `أضِف مفتاح المستشار أو استخدم جهازًا يدعم WebGPU.`,
  );
}

/** تحرير موارد المحرّك المحليّ (يُستدعى عند إغلاق النافذة أو التبديل). */
export async function disposeLocal(): Promise<void> {
  await localProvider.dispose?.();
}
