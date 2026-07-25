# Study League — Product Requirements

## 1. Summary

Study League is a mobile-first study productivity app: a subject-based focus timer, daily
planner, and statistics engine wrapped in a social layer (friends, groups, live presence)
and a **seasonal league system** that rewards *sustainable consistency* — goal completion,
verified focus, and task execution — rather than raw hours.

**Positioning statement:** for students who find solo study lonely and raw-hours
leaderboards demoralizing or unhealthy, Study League turns steady, planned work into
visible, fair competitive progress.

## 2. Problems we solve

| Problem | Today | Study League |
|---|---|---|
| "Did I actually study?" | Guessing, retroactive logging | Verified timer with event-level audit trail |
| Planning vs doing gap | Plans live in a separate app | Tasks, estimates, and planned-vs-actual in the same loop |
| Leaderboards reward burnout | Rank = total hours | League Points cap hour benefits; consistency & goals dominate |
| Studying alone | No accountability | Presence, groups, live rooms, reactions |
| Cheating ruins competition | Manual entries count fully | Manual time = 0 competitive credit; anomaly flagging; transparent exclusions |

## 3. Users

- **University students** balancing coursework and exams.
- **Exam preppers** (entrance exams, standardized tests, professional certifications) with
  hard target dates (D-Day).
- **Self-taught learners** (software engineering, languages) needing long-horizon consistency.

## 4. Core loops

1. **Daily loop:** open Today → see goal progress & tasks → Start Studying → focus session
   (Pomodoro or stopwatch) → session note → task check-off → reflection.
2. **Weekly loop:** review Insights → adjust scheduled study days & goals → watch weekly
   League Points accrue → finish missions.
3. **Seasonal loop (4 weeks):** placement → climb cohort leaderboard → promotion /
   retention / relegation → season summary → next season.

## 5. Feature areas

### 5.1 Authentication & onboarding
Email/password now; Google & Apple as pluggable identity providers. Onboarding captures
username, display name, time zone, country/language, study category, daily & weekly goals,
scheduled study days, privacy defaults, notification preferences.

### 5.2 Subjects & timer
Subject CRUD (color, order, archive). Stopwatch and configurable Pomodoro. Pause/resume/
stop, session notes, "went as planned" marker. Timer survives app kill and device restart;
works fully offline; syncs idempotently. Manual entries allowed but permanently labeled.
Elapsed time is **always** computed from persisted timestamps — never an interval counter.
One active session per user, enforced by a database constraint.

### 5.3 Focus protection
Platform abstraction: allowed-app list, distraction-block mode, background-transition
detection. Capabilities are feature-flagged per platform; unsupported = visibly disabled,
never simulated.

### 5.4 Planner & tasks
Daily tasks with subject link, estimate, priority, ordering, defer/copy-forward, timeline
view, planned-vs-actual, daily reflection.

### 5.5 Statistics
Day/week/month/year; calendar heatmap; verified vs manual split; subject breakdown; goal
completion rate; current/longest streak; average session length; focus completion rate;
planned vs actual; productive-time histograms; week-over-week deltas. All aggregation in
the user's time zone.

### 5.6 Social
Friend requests, user search, block/report. Groups (public/private/invite-code) with
roles, rules, member presence, daily/weekly group rankings, encouragement reactions.

### 5.7 Live study room
Real-time room: who studies what, verified duration, break status, goal progress,
reactions. Camera accountability is a **later, opt-in** phase — interface reserved, no
always-on video.

### 5.8 Rankings & leagues
See §6. Raw-duration boards exist but League Points are the headline ranking.

### 5.9 Community
Moderated topic posts, comments, reactions, bookmarks, reports, soft deletion. Post-MVP.

### 5.10 D-Day goals
Goal + target date + weekly hours + milestones + countdown.

## 6. The League (differentiator)

- **Seasons:** 4 weeks. **Divisions:** Bronze → Silver → Gold → Platinum → Diamond →
  Master. **Cohorts:** 20–30 users matched within a league category
  (software engineering, university, entrance exams, standardized tests, languages,
  professional certs, general productivity — extensible via data, not code).
- **Weekly score = 0–1000 League Points:**
  - Goal completion — up to **400**
  - Consistency across *scheduled* study days — up to **250**
  - Completed focus sessions — up to **150**
  - Planned task completion — up to **150**
  - Positive group participation — up to **50**
- **Fairness rules:** benefit from hours is capped; rest days the user scheduled are never
  penalized; manual time earns zero competitive credit; flagged time is excluded with an
  explanation; scoring weights are versioned so past seasons stay reproducible; all
  calculation is server-side, deterministic, and unit-tested.
- **Season end:** top performers promote, middle retains, bottom relegates, inactive →
  unranked, new users → provisional placement. Thresholds configurable.
- **Missions** nudge healthy behavior ("study on 5 scheduled days", "complete a session
  before noon", "recover after missing a day") — never raw screen-time maximization.

## 7. Integrity & safety

Event-level session audit trail; device hash; server receipt times; anomaly flags
(overlaps, impossible sequences, marathon sessions, retro-edit abuse, repeated offline
bursts). Suspicious records are **marked, never silently deleted**; users are told when a
record is excluded from scoring; score-affecting changes append to an immutable audit log.
No invasive surveillance.

## 8. Non-goals (v1)

Always-on video, web client, tutor marketplace, paid subscriptions, AI study advice,
full community implementation.

## 9. Success metrics

- D7 retention of users who complete ≥1 verified session on day 1.
- Median verified minutes per *scheduled* study day (not total hours).
- Weekly goal completion rate.
- % of league participants returning for a second season.
- Planned-task completion rate.

## 10. Release milestones

**M1 (this repo, now):** monorepo, infra, auth, profile/settings, subjects, resilient
offline-first timer, sync, Today dashboard, daily/weekly stats, basic tasks, seed data,
CI, scoring domain (unexposed).
**M2:** friends, groups, Redis presence, WebSocket fan-out, notifications.
**M3:** leagues end-to-end (placement, cohorts, weekly scoring jobs, missions, season
close), rankings UI.
**M4:** community, D-Day goals, focus protection deep integrations, web dashboard.
