"use client";

import { useActionState, useState } from "react";
import { ArrowRight, Check, LoaderCircle, Mail } from "lucide-react";
import { sendSignInLink, updateTopics } from "@/app/actions";
import type { Profile } from "@/lib/types";

const descriptions: Record<string, string> = {
  llm: "Models, reasoning, and fine-tuning",
  agents: "Tools, workflows, and autonomy",
  vision: "Images, video, and multimodal AI",
  open_source: "Open models and practical releases",
  research: "Papers, benchmarks, and new methods",
  policy: "Safety, governance, and regulation",
  robotics: "Embodied AI and the physical world",
  infrastructure: "Serving, compute, and deployment",
};
export function TopicForm({
  profile,
  demo,
}: {
  profile: Profile;
  demo: boolean;
}) {
  const [selected, setSelected] = useState(profile.topics);
  const [state, action, pending] = useActionState(updateTopics, {});
  return (
    <form action={action}>
      <div className="section-heading">
        <h2>Build your reading lens</h2>
        <span className="count-pill">
          {selected.length} / {profile.topic_limit} selected
        </span>
      </div>
      <p className="muted">
        Choose the areas you want to follow. You can change them anytime.
      </p>
      <div className="topic-grid">
        {profile.available_topics.map((topic) => {
          const checked = selected.includes(topic.id);
          return (
            <label
              className={`topic-choice ${checked ? "selected" : ""}`}
              key={topic.id}
            >
              <input
                type="checkbox"
                name="topics"
                value={topic.id}
                checked={checked}
                disabled={
                  pending ||
                  (!checked && selected.length >= profile.topic_limit)
                }
                onChange={() =>
                  setSelected((current) =>
                    checked
                      ? current.filter((value) => value !== topic.id)
                      : [...current, topic.id],
                  )
                }
              />
              <span className="checkbox-mark">
                {checked && <Check size={14} />}
              </span>
              <span>
                <strong>{topic.label}</strong>
                <small>{descriptions[topic.id]}</small>
              </span>
            </label>
          );
        })}
      </div>
      <div className="form-footer">
        <p className="muted">
          {demo
            ? "Demo selections stay in this browser."
            : "Preferences are saved to your account."}
        </p>
        <button className="button primary" disabled={pending}>
          {pending && <LoaderCircle className="spin" size={16} />}
          {pending ? "Saving…" : "Save preferences"}
          <ArrowRight size={16} />
        </button>
      </div>
      {state.error && (
        <p className="form-error" role="alert">
          {state.error}
        </p>
      )}
      {state.success && (
        <p className="form-success" role="status">
          {state.success}
        </p>
      )}
    </form>
  );
}
export function LoginForm({ configured }: { configured: boolean }) {
  const [state, action, pending] = useActionState(sendSignInLink, {});
  return (
    <form action={action} className="login-form">
      <label htmlFor="email">Email address</label>
      <div className="input-wrap">
        <Mail size={18} />
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          required
          maxLength={320}
          disabled={!configured || pending}
        />
      </div>
      <button className="button primary" disabled={!configured || pending}>
        {pending ? "Sending…" : "Email me a sign-in link"}
        <ArrowRight size={17} />
      </button>
      {state.error && (
        <p className="form-error" role="alert">
          {state.error}
        </p>
      )}
      {state.success && (
        <p className="form-success" role="status">
          {state.success}
        </p>
      )}
    </form>
  );
}
