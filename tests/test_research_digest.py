import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "research_digest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("research_digest", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["research_digest"] = module
    spec.loader.exec_module(module)
    return module


class ResearchDigestTests(unittest.TestCase):
    def test_load_env_values_handles_quotes_and_comments(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\nTAVILY_API_KEY='abc123'\nOTHER=\"value\"\nEMPTY=\n",
                encoding="utf-8",
            )
            module = load_module()

            values = module.load_env_values(env_path, ["TAVILY_API_KEY", "OTHER", "MISSING"])

        self.assertEqual(values, {"TAVILY_API_KEY": "abc123", "OTHER": "value"})

    def test_dedupe_candidates_removes_same_url_and_near_duplicate_titles(self):
        module = load_module()
        candidates = [
            {"title": "Claude Code releases new terminal feature", "url": "https://example.com/a?utm_source=x", "score": 0.9},
            {"title": "Claude Code releases new terminal feature", "url": "https://example.com/a?utm_campaign=y", "score": 0.8},
            {"title": "Claude Code new terminal feature released", "url": "https://example.com/b", "score": 0.7},
            {"title": "Ollama Cloud adds model catalogue updates", "url": "https://example.com/c", "score": 0.6},
        ]

        result = module.dedupe_candidates(candidates)

        self.assertEqual(
            [item["url"] for item in result],
            ["https://example.com/a?utm_source=x", "https://example.com/c"],
        )

    def test_score_candidate_prioritises_official_and_workflow_relevant_sources(self):
        module = load_module()
        official = {
            "title": "Hermes Agent adds cron improvements for daily briefing bots",
            "url": "https://hermes-agent.nousresearch.com/docs/guides/daily-briefing-bot",
            "content": "Cron jobs, Telegram delivery, daily briefing automation",
            "lane": "Hermes Agent and personal-agent ops",
            "search_score": 0.7,
        }
        fluff = {
            "title": "AI startup raises funding for enterprise transformation",
            "url": "https://random-pr.example.com/story",
            "content": "Funding round and enterprise AI press release",
            "lane": "AI devtools and agent frameworks",
            "search_score": 0.9,
        }

        self.assertGreater(module.score_candidate(official), module.score_candidate(fluff))

    def test_select_candidates_filters_social_noise_and_deferred_tools(self):
        module = load_module()
        candidates = [
            {
                "title": "Instagram hype reel about agents",
                "url": "https://www.instagram.com/p/example",
                "content": "Vague agent hype",
                "lane": "AI devtools and agent frameworks",
                "search_score": 0.99,
            },
            {
                "title": "composio: SDK for agent integrations",
                "url": "https://github.com/warpdot-dev/composio",
                "content": "Composio TypeScript Python SDK AI agents integration catalogue",
                "lane": "AI devtools and agent frameworks",
                "search_score": 0.98,
            },
            {
                "title": "Random AI Team OS repository",
                "url": "https://github.com/random/ai-team-os",
                "content": "Multi-agent team templates and dashboard",
                "lane": "AI devtools and agent frameworks",
                "search_score": 0.97,
            },
            {
                "title": "Hermes Agent workspace 2.0 released",
                "url": "https://github.com/NousResearch/hermes-agent/releases/tag/v2.0.0",
                "content": "Release notes mention cron delivery to Telegram and workspace updates",
                "lane": "Hermes Agent and personal-agent ops",
                "search_score": 0.96,
            },
            {
                "title": "OpenClaw release adds Claude importer",
                "url": "https://github.com/openclaw/openclaw/releases",
                "content": "Release notes for Claude Code importer and MCP migration",
                "lane": "Claude Code, OpenAI Codex, OpenCode, OpenClaw",
                "search_score": 0.95,
            },
            {
                "title": "Ollama Cloud adds model catalogue updates",
                "url": "https://ollama.com/blog/model-catalogue",
                "content": "Ollama Cloud model catalogue update for Kimi, Qwen, and coding agents",
                "lane": "Ollama Cloud, Kimi, Qwen, GLM, local/open-weight models",
                "search_score": 0.94,
            },
        ]

        selected = module.select_candidates(candidates, limit=3)
        selected_urls = {item["url"] for item in selected}
        selected_sources = {item["source"] for item in selected}

        self.assertNotIn("instagram.com", selected_sources)
        self.assertNotIn("https://github.com/warpdot-dev/composio", selected_urls)
        self.assertNotIn("https://github.com/random/ai-team-os", selected_urls)
        self.assertEqual(len({item["lane"] for item in selected}), 3)

    def test_score_candidate_prioritises_releases_over_static_github_blobs(self):
        module = load_module()
        release = {
            "title": "OpenClaw release adds Claude Code importer",
            "url": "https://github.com/openclaw/openclaw/releases",
            "content": "Release notes for Claude Code importer and MCP migration",
            "lane": "Claude Code, OpenAI Codex, OpenCode, OpenClaw",
            "search_score": 0.8,
        }
        blob = {
            "title": "Coding Agent skill file",
            "url": "https://github.com/openclaw/openclaw/blob/main/skills/coding-agent/SKILL.md",
            "content": "Static skill file for a coding agent",
            "lane": "Claude Code, OpenAI Codex, OpenCode, OpenClaw",
            "search_score": 0.8,
        }

        self.assertGreater(module.score_candidate(release), module.score_candidate(blob))

    def test_excluded_candidate_filters_github_topic_and_awesome_star_noise(self):
        module = load_module()
        noise = [
            {"title": "ai-agents-framework · GitHub Topics", "url": "https://github.com/topics/ai-agents-framework", "content": "Topic directory"},
            {"title": "awesome-cli-coding-agents", "url": "https://github.com/bradAGI/awesome-cli-coding-agents", "content": "Curated list"},
            {"title": "my-awesome-stars", "url": "https://github.com/r0xsh/my-awesome-stars", "content": "Star archive"},
            {"title": "AI Team OS", "url": "https://github.com/CronusL-1141/AI-company", "content": "Random root repo"},
            {"title": "Model: add strict gpt-5.3-codex fallback", "url": "https://github.com/openclaw/openclaw/pull/9989", "content": "Pull request page without dated release evidence"},
        ]

        self.assertTrue(all(module.is_excluded_candidate(item) for item in noise))

    def test_clean_content_strips_github_avatar_boilerplate_and_caps_length(self):
        module = load_module()
        raw = "* [![@user](https://avatars.githubusercontent.com/u/1?s=64&v=4)](https://github.com/user). " + "Useful release note. " * 200

        cleaned = module.clean_content(raw, max_chars=120)

        self.assertNotIn("avatars.githubusercontent.com", cleaned)
        self.assertLessEqual(len(cleaned), 121)
        self.assertIn("Useful release note", cleaned)

    def test_run_tavily_search_passes_domain_filters(self):
        from unittest.mock import patch

        module = load_module()

        with patch.object(module.subprocess, "check_output", return_value=b'{"results": []}') as mocked:
            module.run_tavily_search(
                "Hermes Agent daily briefing",
                {},
                max_results=3,
                time_range="week",
                include_domains=["hermes-agent.nousresearch.com", "github.com"],
                exclude_domains=["composio.dev"],
            )

        command = mocked.call_args.args[0]
        self.assertIn("--include-domains", command)
        self.assertIn("hermes-agent.nousresearch.com,github.com", command)
        self.assertIn("--exclude-domains", command)
        self.assertIn("composio.dev", command)

    def test_render_digest_outputs_telegram_markdown_and_html(self):
        import tempfile

        module = load_module()
        selected = [
            {
                "title": "Hermes Agent daily briefing pattern",
                "url": "https://hermes-agent.nousresearch.com/docs/guides/daily-briefing-bot",
                "source": "hermes-agent.nousresearch.com",
                "lane": "Hermes Agent and personal-agent ops",
                "content": "Cron prompts must be self-contained and can deliver to Telegram.",
                "final_score": 12.3,
            }
        ]
        payload = {
            "date_label": "Saturday 2 May",
            "generated_at": "2026-05-02T22:30:00+01:00",
            "candidates_considered": 12,
            "sources_considered": 6,
            "selected": selected,
            "query_count": 5,
        }

        with tempfile.TemporaryDirectory() as tmp:
            rendered = module.render_digest(payload, Path(tmp))
            self.assertIn("☀️ Good morning", rendered["telegram"])
            self.assertIn("🧠 AI/Agent brief", rendered["telegram"])
            self.assertIn("Practical recommendation", rendered["markdown"])
            self.assertIn("<!doctype html>", rendered["html"])
            self.assertIn("KENSEI AI/Agent Brief", rendered["html"])
            self.assertTrue((Path(tmp) / "research-digest.md").exists())
            self.assertTrue((Path(tmp) / "research-digest.html").exists())

    def test_telegram_fallback_keeps_five_compact_signals(self):
        module = load_module()
        selected = []
        for idx in range(5):
            selected.append(
                {
                    "title": f"Very long research signal title {idx} " + "x" * 120,
                    "url": f"https://example.com/story-{idx}",
                    "source": "example.com",
                    "lane": "AI devtools and agent frameworks",
                    "content": "Useful but verbose content. " * 80,
                    "final_score": 10 - idx,
                }
            )
        payload = {
            "date_label": "Saturday 2 May",
            "generated_at": "2026-05-02T22:30:00+01:00",
            "candidates_considered": 20,
            "sources_considered": 5,
            "selected": selected,
            "query_count": 5,
        }

        text = module.telegram_text(payload, Path("/tmp/research-digest.html"))

        self.assertIn("1. Very long research signal title 0", text)
        self.assertIn("📎 HTML brief", text)
        self.assertLessEqual(len(text), 1400)

    def test_latest_commit_history_is_not_news_signal(self):
        module = load_module()
        candidate = {
            "title": "GitHub - example/random-agent",
            "url": "https://github.com/example/random-agent",
            "source": "github.com",
            "lane": "Agent frameworks and devtools",
            "content": "Latest commit History 957 Commits. Search code, repositories, users.",
        }

        self.assertFalse(module.has_news_signal(candidate))
        self.assertTrue(module.is_excluded_candidate(candidate))

    def test_telegram_media_tag_attaches_full_brief_when_requested(self):
        module = load_module()
        payload = {
            "date_label": "Saturday 2 May",
            "generated_at": "2026-05-02T22:30:00+01:00",
            "time_range_used": "day",
            "candidates_considered": 1,
            "sources_considered": 1,
            "selected": [
                {
                    "title": "OpenClaw 2.1.4 released",
                    "url": "https://github.com/openclaw/openclaw/releases/tag/v2.1.4",
                    "source": "github.com",
                    "lane": "Coding agents and CLIs",
                    "content": "Release notes for OpenClaw 2.1.4",
                    "final_score": 20,
                }
            ],
            "query_count": 5,
        }

        text = module.telegram_text(payload, Path("/tmp/research-digest.html"), include_media_tag=True)

        self.assertIn("📎 HTML brief attached", text)
        self.assertIn("MEDIA:/tmp/research-digest.html", text)

    def test_topic_queries_use_abc_lanes(self):
        module = load_module()

        self.assertEqual(module.LANE_ORDER, ["A: AI News", "B: Tool News", "C: MyTool"])
        self.assertEqual({topic["lane"] for topic in module.TOPIC_QUERIES}, set(module.LANE_ORDER))

    def test_collect_rss_feed_parses_items_and_sends_user_agent(self):
        from io import BytesIO
        from unittest.mock import patch

        module = load_module()
        xml = b"""<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Claude Code 2.1 released</title>
            <link>https://example.com/claude-code-2-1</link>
            <description>120 points, 34 comments. Release notes for Claude Code.</description>
            <pubDate>Sun, 03 May 2026 10:55:30 +0000</pubDate>
          </item>
        </channel></rss>
        """

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(module.urllib.request, "urlopen", return_value=Response(xml)) as mocked:
            candidates = module.collect_rss_feed(
                {"url": "https://www.reddit.com/r/ClaudeAI/.rss", "lane": "C: MyTool", "name": "r/ClaudeAI"},
                max_items=3,
            )

        request = mocked.call_args.args[0]
        self.assertIn("KENSEI", request.get_header("User-agent"))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["lane"], "C: MyTool")
        self.assertEqual(candidates[0]["source_type"], "rss")
        self.assertEqual(candidates[0]["points"], 120)
        self.assertEqual(candidates[0]["comments"], 34)

    def test_excluded_candidate_blocks_press_wires_and_seo_comparison_pages(self):
        module = load_module()
        noise = [
            {
                "title": "AI Startup Announces Enterprise Automation Partnership",
                "url": "https://www.openpr.com/news/123/ai-startup-announces-partnership",
                "content": "Press release distributed by openPR about enterprise AI transformation.",
                "lane": "A: AI News",
            },
            {
                "title": "Claude Code vs OpenAI Codex: Pricing and Alternatives Compared",
                "url": "https://example-seo.com/claude-code-vs-openai-codex-alternatives",
                "content": "A comparison page with pricing, alternatives, and generic affiliate SEO copy.",
                "lane": "C: MyTool",
            },
            {
                "title": "Morningstar says AI platform shares move after vague announcement",
                "url": "https://www.morningstar.com/news/globe-newswire/123/ai-platform-announcement",
                "content": "GlobeNewswire press release carried by Morningstar.",
                "lane": "A: AI News",
            },
        ]

        self.assertTrue(all(module.is_excluded_candidate(item) for item in noise))

    def test_excluded_candidate_blocks_static_aggregator_pages(self):
        module = load_module()
        noise = [
            {
                "title": "nltpt-q (nltpt-q)",
                "url": "https://huggingface.co/organizations/nltpt-q/activity/all",
                "content": "Organisation activity page with model uploads and likes.",
                "lane": "A: AI News",
            },
            {
                "title": "Cloud, Thinking models · Ollama",
                "url": "https://ollama.com/search?c=cloud&c=thinking",
                "content": "Static model catalogue search page.",
                "lane": "A: AI News",
            },
            {
                "title": "glm-5.1:cloud",
                "url": "https://ollama.com/library/glm-5.1:cloud",
                "content": "Static model library page without a dated release note.",
                "lane": "A: AI News",
            },
            {
                "title": "4.14 kB - Hugging Face",
                "url": "https://huggingface.co/datasets/joylarkin/AI-Coding-Models/resolve/main/aicodingmodels.csv?download=true",
                "content": "Raw CSV download, not a news item.",
                "lane": "A: AI News",
            },
            {
                "title": "model: x-ai/grok-code-fast-1",
                "url": "https://huggingface.co/spaces/bigcode/arena/raw/ba99c06a66f7f9559c8df45b281cd3c764f2de45/api_config.yaml",
                "content": "Raw YAML config, not a news item.",
                "lane": "A: AI News",
            },
        ]

        self.assertTrue(all(module.is_excluded_candidate(item) for item in noise))

    def test_excluded_candidate_blocks_reddit_discussion_sludge(self):
        module = load_module()
        noise = [
            {
                "title": "GPT 5.5 just leaked its chain of thought to me in codex",
                "url": "https://www.reddit.com/r/LocalLLaMA/comments/example/gpt_55_leaked_cot/",
                "source": "reddit.com",
                "content": "Speculation and drama, not a release or changelog.",
                "source_type": "rss",
                "feed_name": "r/LocalLLaMA",
                "lane": "A: AI News",
            },
            {
                "title": "Let's not rename powershell.exe",
                "url": "https://www.reddit.com/r/ClaudeAI/comments/example/lets_not_rename_powershellexe/",
                "source": "reddit.com",
                "content": "Anecdotal debugging thread without a versioned release or product update.",
                "source_type": "rss",
                "feed_name": "r/ClaudeAI",
                "lane": "C: MyTool",
            },
            {
                "title": "New version 2026.5.2",
                "url": "https://www.reddit.com/r/openclaw/comments/example/new_version_202652/",
                "source": "reddit.com",
                "content": "Has anyone updated to version 2026.5.2? Have they fixed the slowdown and Gateway issues?",
                "source_type": "rss",
                "feed_name": "r/OpenClaw",
                "lane": "C: MyTool",
            },
            {
                "title": "Upgrade Safely - How to setup a canary instance",
                "url": "https://www.reddit.com/r/openclaw/comments/example/upgrade_safely/",
                "source": "reddit.com",
                "content": "I am tired of reading all the complaints from people having issues with upgrading.",
                "source_type": "rss",
                "feed_name": "r/OpenClaw",
                "lane": "C: MyTool",
            },
        ]
        signal = {
            "title": "OpenClaw new version 2026.5.2 released",
            "url": "https://www.reddit.com/r/openclaw/comments/example/new_version_202652/",
            "source": "reddit.com",
            "content": "Release notes for OpenClaw version 2026.5.2.",
            "source_type": "rss",
            "feed_name": "r/OpenClaw",
            "lane": "C: MyTool",
        }

        self.assertTrue(all(module.is_excluded_candidate(item) for item in noise))
        self.assertFalse(module.is_excluded_candidate(signal))

    def test_rss_window_rejects_stale_items(self):
        module = load_module()
        now = module.datetime(2026, 5, 3, 12, 0, tzinfo=module.ZoneInfo("Europe/London"))

        self.assertTrue(module.rss_item_within_time_range("Sun, 03 May 2026 10:55:30 +0000", "day", now))
        self.assertFalse(module.rss_item_within_time_range("Thu, 23 Apr 2026 17:57:18 +0000", "week", now))
        self.assertFalse(module.rss_item_within_time_range("", "day", now))

    def test_low_signal_payload_renders_silent(self):
        module = load_module()
        payload = {
            "date_label": "Sunday 3 May",
            "generated_at": "2026-05-03T08:15:00+01:00",
            "time_range_used": "day + week fallback",
            "candidates_considered": 9,
            "sources_considered": 4,
            "min_signal_count": 3,
            "selected": [
                {
                    "title": "OpenClaw 2.1.4 released",
                    "url": "https://github.com/openclaw/openclaw/releases/tag/v2.1.4",
                    "source": "github.com",
                    "lane": "C: MyTool",
                    "content": "Release notes for OpenClaw 2.1.4",
                    "final_score": 20,
                }
            ],
        }

        self.assertEqual(module.telegram_text(payload, Path("/tmp/research-digest.html")), "[SILENT]")


if __name__ == "__main__":
    unittest.main()
