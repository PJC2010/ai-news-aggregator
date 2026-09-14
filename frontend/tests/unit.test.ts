import { test } from "node:test";
import assert from "node:assert/strict";
import { feedHref, parseFilters, safeUrl } from "../lib/format.ts";

test("source links reject executable and credential-bearing URLs", () => {
  for (const url of [
    "javascript:alert(1)",
    "data:text/html,hello",
    "file:///etc/passwd",
    "//example.com",
    "https://user:pass@example.com",
    "not a url",
  ])
    assert.equal(safeUrl(url), null);
  assert.equal(
    safeUrl("https://example.com/paper?q=one"),
    "https://example.com/paper?q=one",
  );
});
test("filters normalize invalid values and ignore ambiguous repeated parameters", () => {
  const filters = parseFilters({
    q: ["a", "b"],
    page: "Infinity",
    window: "wrong",
    sort: "wrong",
    event_type: "wrong",
    following: "yes",
  });
  assert.deepEqual(filters, {
    q: "",
    page: 1,
    window: "week",
    sort: "ranked",
    event_type: "",
    following: false,
    topic: "",
  });
  assert.equal(parseFilters({ page: "2.5" }).page, 1);
  assert.equal(parseFilters({ q: "a".repeat(500) }).q.length, 200);
});
test("pagination preserves the chosen search, period, topic, and sort", () => {
  const filters = parseFilters({
    q: "R&D 100%",
    topic: "agents",
    following: "true",
    window: "all",
    sort: "latest",
  });
  const url = new URL(feedHref(filters, { page: 2 }), "http://localhost");
  assert.equal(url.searchParams.get("q"), "R&D 100%");
  assert.equal(url.searchParams.get("topic"), "agents");
  assert.equal(url.searchParams.get("following"), "true");
  assert.equal(url.searchParams.get("page"), "2");
});
