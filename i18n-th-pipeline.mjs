#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

const PLACEHOLDER_RE =
  /(\{\{\s*[\w.$-]+\s*\}\}|\{[A-Za-z0-9_.-]+\}|\{[0-9]+\}|\$\{[A-Za-z0-9_.-]+\}|%[sdifjoO]|:\w+|<[^>]+>)/g;

const args = parseArgs(process.argv.slice(2));
const command = args._[0];

if (!command || ["extract", "translate", "merge", "validate"].includes(command) === false) {
  usage();
  process.exit(command ? 1 : 0);
}

const literalsPath = requiredArg("literals");
const outDir = path.resolve(args.outDir || "th-i18n-work");
const langEn = args.enKey || "en";
const langZhTw = args.zhTwKey || "zh_tw";
const langTh = args.thKey || "th";

if (command === "extract") {
  const data = readJson(literalsPath);
  const entries = extractEntries(data, { langEn, langZhTw, langTh });
  const batchSize = Number(args.batchSize || 150);
  fs.mkdirSync(path.join(outDir, "chunks"), { recursive: true });
  writeJson(path.join(outDir, "entries.json"), entries);
  writeChunks(entries, batchSize, path.join(outDir, "chunks"));
  console.log(`Extracted ${entries.length} entries into ${path.join(outDir, "chunks")}`);
}

if (command === "translate") {
  const chunksDir = path.resolve(args.chunksDir || path.join(outDir, "chunks"));
  const translatedDir = path.resolve(args.translatedDir || path.join(outDir, "translated"));
  const gptCommand = args.gptCommand || process.env.GPT_CLI_COMMAND || "gpt";
  fs.mkdirSync(translatedDir, { recursive: true });

  const chunkFiles = fs
    .readdirSync(chunksDir)
    .filter((file) => file.endsWith(".json"))
    .sort((a, b) => a.localeCompare(b));

  for (const file of chunkFiles) {
    const inputPath = path.join(chunksDir, file);
    const outputPath = path.join(translatedDir, file);
    if (fs.existsSync(outputPath) && !args.force) {
      console.log(`Skip existing ${outputPath}`);
      continue;
    }

    const chunk = readJson(inputPath);
    const prompt = buildTranslationPrompt(chunk);
    console.log(`Translating ${file} (${chunk.length} entries)`);
    const stdout = await runCli(gptCommand, prompt);
    const json = parseJsonFromModel(stdout);
    validateTranslatedChunk(chunk, json);
    writeJson(outputPath, json);
  }
}

if (command === "merge") {
  const data = readJson(literalsPath);
  const translatedDir = path.resolve(args.translatedDir || path.join(outDir, "translated"));
  const outputPath = path.resolve(args.output || path.join(outDir, "literals.with-th.json"));
  const translations = readTranslations(translatedDir);
  const merged = mergeTranslations(data, translations, { langEn, langZhTw, langTh });
  const report = validateLiterals(merged, { langEn, langZhTw, langTh });

  if (report.errors.length > 0) {
    writeJson(path.join(outDir, "validation-errors.json"), report);
    console.error(`Validation failed: ${report.errors.length} errors`);
    process.exit(1);
  }

  writeJson(outputPath, merged);
  console.log(`Merged ${translations.size} translations into ${outputPath}`);
}

if (command === "validate") {
  const data = readJson(args.file || literalsPath);
  const report = validateLiterals(data, { langEn, langZhTw, langTh });
  writeJson(path.join(outDir, "validation-report.json"), report);
  if (report.errors.length > 0) {
    console.error(`Validation failed: ${report.errors.length} errors`);
    process.exit(1);
  }
  console.log(`Validation passed: ${report.checked} entries checked`);
}

function usage() {
  console.log(`
Usage:
  node i18n-th-pipeline.mjs extract --literals D:\\WAP_ssa\\jsx\\sys\\locale\\literals.json --outDir work-th --batchSize 150
  node i18n-th-pipeline.mjs translate --literals D:\\WAP_ssa\\jsx\\sys\\locale\\literals.json --outDir work-th --gptCommand "gpt"
  node i18n-th-pipeline.mjs merge --literals D:\\WAP_ssa\\jsx\\sys\\locale\\literals.json --outDir work-th --output D:\\WAP_ssa\\jsx\\sys\\locale\\literals.th.json
  node i18n-th-pipeline.mjs validate --literals D:\\WAP_ssa\\jsx\\sys\\locale\\literals.th.json --outDir work-th

Options:
  --enKey       Source English language key. Default: en
  --zhTwKey     Source Traditional Chinese language key. Default: zh_tw
  --thKey       Target Thai language key. Default: th
  --batchSize   Entries per chunk for extract. Default: 150
`);
}

function parseArgs(argv) {
  const parsed = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      parsed._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      i += 1;
    }
  }
  return parsed;
}

function requiredArg(name) {
  if (!args[name]) {
    console.error(`Missing required --${name}`);
    usage();
    process.exit(1);
  }
  return path.resolve(args[name]);
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

function extractEntries(data, langs) {
  if (isRootLocaleShape(data, langs)) {
    return extractRootLocaleEntries(data, langs);
  }
  return extractRecordEntries(data, langs);
}

function isRootLocaleShape(data, { langEn, langZhTw }) {
  return isPlainObject(data?.[langEn]) && isPlainObject(data?.[langZhTw]);
}

function extractRootLocaleEntries(data, { langEn, langZhTw, langTh }) {
  const entries = [];
  const enLeaves = flattenLeafStrings(data[langEn]);
  const zhLeaves = flattenLeafStrings(data[langZhTw]);
  const thLeaves = flattenLeafStrings(data[langTh] || {});

  for (const [leafPath, en] of enLeaves.entries()) {
    const zhTw = zhLeaves.get(leafPath);
    const existingTh = thLeaves.get(leafPath);
    if (typeof zhTw !== "string" || typeof existingTh === "string") continue;
    entries.push({
      mode: "rootLocale",
      path: leafPath,
      en,
      zh_tw: zhTw,
      placeholders: placeholders(en, zhTw),
    });
  }
  return entries;
}

function extractRecordEntries(data, { langEn, langZhTw, langTh }) {
  const entries = [];
  walk(data, [], (node, pathParts) => {
    if (!isPlainObject(node)) return;
    if (typeof node[langEn] !== "string" || typeof node[langZhTw] !== "string") return;
    if (typeof node[langTh] === "string" && node[langTh].trim()) return;
    entries.push({
      mode: "record",
      path: pathParts.join("."),
      en: node[langEn],
      zh_tw: node[langZhTw],
      placeholders: placeholders(node[langEn], node[langZhTw]),
    });
  });
  return entries;
}

function flattenLeafStrings(data) {
  const leaves = new Map();
  walk(data, [], (node, pathParts) => {
    if (typeof node === "string") leaves.set(pathParts.join("."), node);
  });
  return leaves;
}

function walk(node, pathParts, visit) {
  visit(node, pathParts);
  if (!isPlainObject(node) && !Array.isArray(node)) return;
  const entries = Array.isArray(node) ? node.entries() : Object.entries(node);
  for (const [key, value] of entries) {
    walk(value, [...pathParts, String(key)], visit);
  }
}

function writeChunks(entries, batchSize, chunksDir) {
  for (let i = 0; i < entries.length; i += batchSize) {
    const chunk = entries.slice(i, i + batchSize);
    const num = String(i / batchSize + 1).padStart(4, "0");
    writeJson(path.join(chunksDir, `chunk-${num}.json`), chunk);
  }
}

function buildTranslationPrompt(chunk) {
  return `You are translating enterprise system UI literals into Thai.

Rules:
- Return JSON only.
- Return an array with one object per input item.
- Each output object must have exactly: "path" and "th".
- Preserve placeholders, variables, HTML tags, newlines, punctuation tokens, and product codes exactly.
- Translate meaning from both English and Traditional Chinese. Prefer concise natural Thai UI wording.
- Do not add explanations.

Input:
${JSON.stringify(
  chunk.map(({ path: itemPath, en, zh_tw, placeholders: itemPlaceholders }) => ({
    path: itemPath,
    en,
    zh_tw,
    placeholders: itemPlaceholders,
  })),
  null,
  2,
)}`;
}

function runCli(commandLine, stdin) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandLine, {
      shell: true,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`GPT CLI exited with ${code}\n${stderr}`));
      } else {
        resolve(stdout);
      }
    });
    child.stdin.end(stdin);
  });
}

function parseJsonFromModel(text) {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (match) return JSON.parse(match[1]);
    const start = trimmed.indexOf("[");
    const end = trimmed.lastIndexOf("]");
    if (start >= 0 && end > start) return JSON.parse(trimmed.slice(start, end + 1));
    throw new Error("Could not parse JSON array from GPT CLI output");
  }
}

function validateTranslatedChunk(chunk, translated) {
  if (!Array.isArray(translated)) throw new Error("Translated output must be an array");
  const inputByPath = new Map(chunk.map((item) => [item.path, item]));
  const seen = new Set();

  for (const item of translated) {
    if (!item || typeof item.path !== "string" || typeof item.th !== "string") {
      throw new Error("Every translated item must contain string path and th");
    }
    const source = inputByPath.get(item.path);
    if (!source) throw new Error(`Unexpected translated path: ${item.path}`);
    seen.add(item.path);
    assertSamePlaceholders(item.path, source.placeholders, tokenSet(item.th));
  }

  for (const source of chunk) {
    if (!seen.has(source.path)) throw new Error(`Missing translated path: ${source.path}`);
  }
}

function readTranslations(translatedDir) {
  const translations = new Map();
  for (const file of fs.readdirSync(translatedDir).filter((item) => item.endsWith(".json")).sort()) {
    const items = readJson(path.join(translatedDir, file));
    validateTranslatedChunk(
      items.map((item) => ({
        path: item.path,
        placeholders: tokenSet(item.th),
      })),
      items,
    );
    for (const item of items) {
      if (translations.has(item.path)) throw new Error(`Duplicate translation path: ${item.path}`);
      translations.set(item.path, item.th);
    }
  }
  return translations;
}

function mergeTranslations(data, translations, langs) {
  const clone = JSON.parse(JSON.stringify(data));
  if (isRootLocaleShape(clone, langs)) {
    if (!isPlainObject(clone[langs.langTh])) clone[langs.langTh] = {};
    for (const [leafPath, th] of translations.entries()) {
      setByDottedPath(clone[langs.langTh], leafPath, th);
    }
    return clone;
  }

  walk(clone, [], (node, pathParts) => {
    if (!isPlainObject(node)) return;
    const itemPath = pathParts.join(".");
    if (translations.has(itemPath)) node[langs.langTh] = translations.get(itemPath);
  });
  return clone;
}

function validateLiterals(data, langs) {
  const entries = extractEntriesForValidation(data, langs);
  const errors = [];
  for (const entry of entries) {
    if (typeof entry.th !== "string" || !entry.th.trim()) {
      errors.push(`Missing Thai translation at ${entry.path}`);
      continue;
    }
    const expected = placeholders(entry.en, entry.zh_tw);
    const actual = tokenSet(entry.th);
    try {
      assertSamePlaceholders(entry.path, expected, actual);
    } catch (error) {
      errors.push(error.message);
    }
  }
  return { checked: entries.length, errors };
}

function extractEntriesForValidation(data, { langEn, langZhTw, langTh }) {
  if (isRootLocaleShape(data, { langEn, langZhTw })) {
    const enLeaves = flattenLeafStrings(data[langEn]);
    const zhLeaves = flattenLeafStrings(data[langZhTw]);
    const thLeaves = flattenLeafStrings(data[langTh] || {});
    const entries = [];
    for (const [leafPath, en] of enLeaves.entries()) {
      const zhTw = zhLeaves.get(leafPath);
      const th = thLeaves.get(leafPath);
      if (typeof zhTw === "string") {
        entries.push({ path: leafPath, en, zh_tw: zhTw, th });
      }
    }
    return entries;
  }

  const entries = [];
  walk(data, [], (node, pathParts) => {
    if (!isPlainObject(node)) return;
    if (
      typeof node[langEn] === "string" &&
      typeof node[langZhTw] === "string"
    ) {
      entries.push({
        path: pathParts.join("."),
        en: node[langEn],
        zh_tw: node[langZhTw],
        th: node[langTh],
      });
    }
  });
  return entries;
}

function placeholders(...values) {
  const tokens = new Set();
  for (const value of values) {
    for (const token of tokenSet(value)) tokens.add(token);
  }
  return [...tokens].sort();
}

function tokenSet(value) {
  return [...String(value).matchAll(PLACEHOLDER_RE)].map((match) => match[0]).sort();
}

function assertSamePlaceholders(itemPath, expected, actual) {
  const expectedKey = expected.join("\n");
  const actualKey = actual.join("\n");
  if (expectedKey !== actualKey) {
    throw new Error(
      `Placeholder mismatch at ${itemPath}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

function setByDottedPath(target, dottedPath, value) {
  const parts = dottedPath.split(".");
  let node = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const part = parts[i];
    if (!isPlainObject(node[part])) node[part] = {};
    node = node[part];
  }
  node[parts.at(-1)] = value;
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === "[object Object]";
}
