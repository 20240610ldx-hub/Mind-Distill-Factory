const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const pptxgen = require("pptxgenjs");

const [, , htmlPathArg, outPathArg, screenshotDirArg] = process.argv;

if (!htmlPathArg || !outPathArg) {
  console.error("Usage: node scripts/export_html_deck_to_pptx.js <input.html> <output.pptx> [screenshot-dir]");
  process.exit(1);
}

const htmlPath = path.resolve(htmlPathArg);
const outPath = path.resolve(outPathArg);
const screenshotDir = path.resolve(screenshotDirArg || path.join(path.dirname(outPath), "mind-distill-factory-v3-slides"));

function fileUrl(filePath) {
  return `file:///${filePath.replace(/\\/g, "/").replace(/^([A-Za-z]):/, "$1:")}`;
}

async function waitForDeck(page) {
  await page.waitForSelector("deck-stage");
  await page.waitForFunction(() => {
    const deck = document.querySelector("deck-stage");
    return deck && typeof deck.length === "number" && deck.length > 0;
  });
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) {
      await document.fonts.ready.catch(() => {});
    }
  });
}

async function activateSlide(page, index) {
  await page.evaluate((slideIndex) => {
    const deck = document.querySelector("deck-stage");
    const slides = Array.from(deck.querySelectorAll(":scope > section"));
    slides.forEach((slide, i) => {
      if (i === slideIndex) slide.setAttribute("data-deck-active", "");
      else slide.removeAttribute("data-deck-active");
    });
    if (deck.shadowRoot) {
      const overlay = deck.shadowRoot.querySelector(".overlay");
      if (overlay) {
        overlay.removeAttribute("data-visible");
        overlay.style.display = "none";
      }
      const tapzones = deck.shadowRoot.querySelector(".tapzones");
      if (tapzones) tapzones.style.display = "none";
    }
  }, index);
  await page.waitForTimeout(80);
}

async function main() {
  if (!fs.existsSync(htmlPath)) {
    throw new Error(`Input HTML not found: ${htmlPath}`);
  }

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.mkdirSync(screenshotDir, { recursive: true });

  const browserCandidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  ].filter(Boolean);
  const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));

  const browser = await chromium.launch({
    headless: true,
    executablePath,
    args: ["--allow-file-access-from-files", "--disable-gpu"],
  });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });

  await page.goto(fileUrl(htmlPath), { waitUntil: "networkidle" });
  await waitForDeck(page);

  const slideCount = await page.evaluate(() => document.querySelector("deck-stage").length);
  const labels = await page.evaluate(() =>
    Array.from(document.querySelectorAll("deck-stage > section")).map((slide, i) =>
      slide.getAttribute("data-label") || slide.getAttribute("data-screen-label") || `Slide ${i + 1}`,
    ),
  );

  const screenshots = [];
  for (let i = 0; i < slideCount; i += 1) {
    await activateSlide(page, i);
    const shotPath = path.join(screenshotDir, `${String(i + 1).padStart(2, "0")}.jpg`);
    await page.screenshot({
      path: shotPath,
      type: "jpeg",
      quality: 96,
      fullPage: false,
      clip: { x: 0, y: 0, width: 1920, height: 1080 },
    });
    screenshots.push(shotPath);
  }

  await browser.close();

  const pptx = new pptxgen();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "Codex";
  pptx.company = "Mind Distill Factory";
  pptx.subject = "Exported from HTML deck-stage source";
  pptx.title = "Mind Distill Factory v3";
  pptx.lang = "zh-CN";
  pptx.theme = {
    headFontFace: "Noto Serif SC",
    bodyFontFace: "Noto Sans SC",
    lang: "zh-CN",
  };

  pptx.defineLayout({ name: "CUSTOM_WIDE", width: 13.333333, height: 7.5 });
  pptx.layout = "CUSTOM_WIDE";

  screenshots.forEach((shotPath, i) => {
    const slide = pptx.addSlide();
    slide.background = { color: "000000" };
    slide.addImage({ path: shotPath, x: 0, y: 0, w: 13.333333, h: 7.5 });
    slide.addNotes(`Source slide ${i + 1}: ${labels[i] || ""}`);
  });

  await pptx.writeFile({ fileName: outPath });

  console.log(JSON.stringify({
    htmlPath,
    outPath,
    screenshotDir,
    slideCount,
    firstLabel: labels[0],
    lastLabel: labels[labels.length - 1],
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
