import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LanguageProvider } from "@/lib/language";
import i18n from "@/i18n";
import { OnboardingTour } from "./OnboardingTour";

// Pin the tour to English so assertions are language-stable (default is Arabic).
beforeAll(async () => {
  try {
    localStorage.setItem("homeupdater.language", "en");
  } catch {
    /* jsdom always has localStorage */
  }
  await i18n.changeLanguage("en");
});

afterEach(cleanup);

function setup() {
  const onDismiss = vi.fn();
  const onFinish = vi.fn();
  render(
    <LanguageProvider>
      <OnboardingTour onDismiss={onDismiss} onFinish={onFinish} />
    </LanguageProvider>,
  );
  return { onDismiss, onFinish };
}

describe("OnboardingTour", () => {
  it("opens on step 1 as a dialog", () => {
    setup();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Create your app password")).toBeInTheDocument();
  });

  it("advances with Next and returns with Back", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /Next/i }));
    expect(screen.getByText("Scan your home network")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back/i }));
    expect(screen.getByText("Create your app password")).toBeInTheDocument();
  });

  it("ends on the last step via onFinish (not onDismiss)", () => {
    const { onFinish, onDismiss } = setup();
    fireEvent.click(screen.getByRole("button", { name: /Next/i })); // -> step 2
    fireEvent.click(screen.getByRole("button", { name: /Next/i })); // -> step 3
    fireEvent.click(screen.getByRole("button", { name: /Next/i })); // -> step 4 (last)
    expect(screen.getByText("Try the AI Advisor")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Get started/i }));
    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("skips from step 1 via onDismiss", () => {
    const { onDismiss } = setup();
    fireEvent.click(screen.getByText("Skip")); // the text button (not the X aria-label)
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("dismisses on Escape", () => {
    const { onDismiss } = setup();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
