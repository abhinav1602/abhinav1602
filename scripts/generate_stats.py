#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

USERNAME = "abhinav1602"

THEME = {
    "bg": "#0d1117",
    "card_bg": "#161b22",
    "title": "#58a6ff",
    "text": "#f0f6fc",
    "subtext": "#8b949e",
    "accent": "#a5d6ff",
    "green": "#3fb950",
    "border": "#30363d",
    "bar_bg": "#21262d",
    "line": "#58a6ff",
}

LANG_COLORS = {
    "JavaScript": "#f1e05a",
    "Python": "#3572A5",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "TypeScript": "#3178c6",
    "Go": "#00ADD8",
    "PHP": "#4F5D95",
    "Shell": "#89e051",
    "Vue": "#41b883",
    "React": "#61dafb",
    "Jupyter Notebook": "#DA5B0B",
    "Docker": "#384d54",
}


class GraphQLError(Exception):
    pass


def graphql(token, query, variables=None, attempts=4):
    # GitHub's GraphQL API can answer 200 with "errors" (e.g. timeouts) and
    # no data, so treat that as a failure and retry instead of using it.
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    last_err = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
                "Authorization": f"bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                body = json.loads(res.read().decode())
            if body.get("errors") or not body.get("data"):
                raise GraphQLError(json.dumps(body.get("errors") or body)[:500])
            return body["data"]
        except (GraphQLError, urllib.error.URLError, TimeoutError) as e:
            last_err = e
            print(f"GraphQL attempt {attempt + 1}/{attempts} failed: {e}")
            time.sleep(5 * (attempt + 1))
    raise GraphQLError(f"GraphQL request failed after {attempts} attempts: {last_err}")


USER_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    name
    login
    createdAt
    followers { totalCount }
    following { totalCount }
    starredRepositories { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazerCount
        forkCount
        isFork
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      totalCodeReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""


def fetch_data_graphql(token):
    user = None
    nodes = []
    cursor = None
    while True:
        data = graphql(token, USER_QUERY, {"login": USERNAME, "cursor": cursor})
        if not data.get("user"):
            raise GraphQLError(f"User {USERNAME} not found")
        page = data["user"]["repositories"]
        nodes.extend(page["nodes"])
        if user is None:
            user = data["user"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    user["repositories"]["nodes"] = nodes

    # One request per year: a single query with every year aliased in it is
    # heavy enough to time out, which used to silently zero out every stat.
    created_at = datetime.strptime(user["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    yearly = {}
    for year in range(created_at.year, now.year + 1):
        from_dt = max(created_at, datetime(year, 1, 1, tzinfo=timezone.utc))
        to_dt = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        data = graphql(token, YEAR_QUERY, {
            "login": USERNAME,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        yearly[f"year_{year}"] = data["user"]["contributionsCollection"]
    user["yearlyContributions"] = yearly

    return user


def fetch_data_rest():
    headers = {"User-Agent": "Mozilla/5.0"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"

    def get_json(url):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read().decode())
        except Exception:
            return {}

    user_info = get_json(f"https://api.github.com/users/{USERNAME}")
    repos_info = get_json(f"https://api.github.com/users/{USERNAME}/repos?per_page=100")
    if not isinstance(repos_info, list):
        repos_info = []

    total_stars = 0
    total_forks = 0
    lang_sizes = {}

    for r in repos_info:
        total_stars += r.get("stargazers_count", 0)
        total_forks += r.get("forks_count", 0)
        lang = r.get("language")
        if lang:
            lang_sizes[lang] = lang_sizes.get(lang, 0) + 1

    commits_data = get_json(f"https://api.github.com/search/commits?q=author:{USERNAME}")
    prs_data = get_json(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:pr")
    issues_data = get_json(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:issue")

    commits = commits_data.get("total_count", 0)
    prs = prs_data.get("total_count", 0)
    issues = issues_data.get("total_count", 0)
    total_contributions = commits + prs + issues

    events = get_json(f"https://api.github.com/users/{USERNAME}/events/public?per_page=100")
    daily_events = {}
    if isinstance(events, list):
        for e in events:
            d_str = e.get("created_at", "")[:10]
            if d_str:
                daily_events[d_str] = daily_events.get(d_str, 0) + 1

    return {
        "user_info": user_info,
        "repos_info": repos_info,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "lang_sizes": lang_sizes,
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "total_contributions": total_contributions,
        "daily_events": daily_events,
    }


def generate_stats_svg(data):
    if "yearlyContributions" in data:
        total_repos = data["repositories"]["totalCount"]
        total_stars = sum(r["stargazerCount"] for r in data["repositories"]["nodes"])
        total_forks = sum(r["forkCount"] for r in data["repositories"]["nodes"])

        commits = 0
        prs = 0
        issues = 0
        contributions = 0

        for key, yc in data["yearlyContributions"].items():
            if not yc:
                continue
            commits += yc.get("totalCommitContributions", 0)
            prs += yc.get("totalPullRequestContributions", 0)
            issues += yc.get("totalIssueContributions", 0)
            contributions += yc.get("contributionCalendar", {}).get("totalContributions", 0)

    elif "repositories" in data:
        total_repos = data["repositories"]["totalCount"]
        total_stars = sum(r["stargazerCount"] for r in data["repositories"]["nodes"])
        total_forks = sum(r["forkCount"] for r in data["repositories"]["nodes"])
        commits = data["contributionsCollection"]["totalCommitContributions"]
        prs = data["contributionsCollection"]["totalPullRequestContributions"]
        issues = data["contributionsCollection"]["totalIssueContributions"]
        contributions = data["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    else:
        total_repos = data["user_info"].get("public_repos", 0)
        total_stars = data["total_stars"]
        total_forks = data["total_forks"]
        commits = data.get("commits", 0)
        prs = data.get("prs", 0)
        issues = data.get("issues", 0)
        contributions = data.get("total_contributions", 0)

    commits_str = f"{commits:,}" if isinstance(commits, int) else str(commits)
    prs_str = f"{prs:,}" if isinstance(prs, int) else str(prs)
    issues_str = f"{issues:,}" if isinstance(issues, int) else str(issues)
    contributions_str = f"{contributions:,}" if isinstance(contributions, int) else str(contributions)

    svg = f"""<svg width="450" height="220" viewBox="0 0 450 220" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .header {{ font: 600 18px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['title']}; }}
    .stat-label {{ font: 500 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['text']}; }}
    .stat-value {{ font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['accent']}; }}
    .border {{ stroke: {THEME['border']}; stroke-width: 1; }}
    .bg {{ fill: {THEME['bg']}; rx: 10px; }}
  </style>
  <rect x="1" y="1" width="448" height="218" rx="8" class="bg border"/>
  <text x="25" y="38" class="header">My GitHub Stats</text>

  <g transform="translate(25, 60)">
    <!-- Stars -->
    <g transform="translate(0, 0)">
      <text x="0" y="15" class="stat-label">★ Total Stars Earned:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{total_stars}</text>
    </g>
    <!-- Total Contributions -->
    <g transform="translate(0, 25)">
      <text x="0" y="15" class="stat-label">📦 Total Contributions:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{contributions_str}</text>
    </g>
    <!-- Total Commits -->
    <g transform="translate(0, 50)">
      <text x="0" y="15" class="stat-label">📝 Total Commits:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{commits_str}</text>
    </g>
    <!-- Total Repos -->
    <g transform="translate(0, 75)">
      <text x="0" y="15" class="stat-label">📁 Public Repositories:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{total_repos}</text>
    </g>
    <!-- Total Forks -->
    <g transform="translate(0, 100)">
      <text x="0" y="15" class="stat-label">🍴 Total Forks:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{total_forks}</text>
    </g>
    <!-- PRs & Issues -->
    <g transform="translate(0, 125)">
      <text x="0" y="15" class="stat-label">🔀 Pull Requests &amp; Issues:</text>
      <text x="390" y="15" class="stat-value" text-anchor="end">{prs_str} PRs / {issues_str} Issues</text>
    </g>
  </g>
</svg>"""
    return svg


def generate_top_langs_svg(data):
    langs = {}
    if "repositories" in data:
        for repo in data["repositories"]["nodes"]:
            if repo.get("languages") and repo["languages"].get("edges"):
                for edge in repo["languages"]["edges"]:
                    l_name = edge["node"]["name"]
                    l_size = edge["size"]
                    langs[l_name] = langs.get(l_name, 0) + l_size
    else:
        langs = data["lang_sizes"]

    total_size = sum(langs.values()) or 1
    sorted_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:6]

    items_svg = ""
    y_offset = 60
    bar_width = 230

    for name, size in sorted_langs:
        pct = (size / total_size) * 100
        color = LANG_COLORS.get(name, THEME["accent"])
        w = max(4, int((pct / 100) * bar_width))

        items_svg += f"""
    <g transform="translate(25, {y_offset})">
      <circle cx="6" cy="6" r="5" fill="{color}" />
      <text x="18" y="10" class="lang-name">{name}</text>
      <text x="390" y="10" class="lang-pct" text-anchor="end">{pct:.1f}%</text>
      <rect x="130" y="2" width="{bar_width}" height="8" rx="4" fill="{THEME['bar_bg']}"/>
      <rect x="130" y="2" width="{w}" height="8" rx="4" fill="{color}"/>
    </g>"""
        y_offset += 24

    svg = f"""<svg width="450" height="220" viewBox="0 0 450 220" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .header {{ font: 600 18px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['title']}; }}
    .lang-name {{ font: 500 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['text']}; }}
    .lang-pct {{ font: 400 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['subtext']}; }}
    .border {{ stroke: {THEME['border']}; stroke-width: 1; }}
    .bg {{ fill: {THEME['bg']}; rx: 10px; }}
  </style>
  <rect x="1" y="1" width="448" height="218" rx="8" class="bg border"/>
  <text x="25" y="38" class="header">Most Used Languages</text>
  {items_svg}
</svg>"""
    return svg


def calculate_streaks_from_day_map(day_map):
    if not day_map:
        return 0, 0

    sorted_dates = sorted(day_map.keys())
    first_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d").date()
    last_date = datetime.strptime(sorted_dates[-1], "%Y-%m-%d").date()

    max_s = 0
    temp_s = 0
    curr_d = first_date
    while curr_d <= last_date:
        d_str = curr_d.strftime("%Y-%m-%d")
        if day_map.get(d_str, 0) > 0:
            temp_s += 1
            if temp_s > max_s:
                max_s = temp_s
        else:
            temp_s = 0
        curr_d += timedelta(days=1)

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    curr_s = 0
    check_date = today
    if day_map.get(today.strftime("%Y-%m-%d"), 0) == 0 and day_map.get(yesterday.strftime("%Y-%m-%d"), 0) > 0:
        check_date = yesterday

    while day_map.get(check_date.strftime("%Y-%m-%d"), 0) > 0:
        curr_s += 1
        check_date -= timedelta(days=1)

    return curr_s, max_s


def generate_streak_svg(data):
    current_streak = 0
    longest_streak = 0
    total_contributions = 0

    day_map = {}
    if "yearlyContributions" in data:
        for key in sorted(data["yearlyContributions"].keys()):
            yc = data["yearlyContributions"][key]
            if not yc:
                continue
            cal = yc.get("contributionCalendar", {})
            total_contributions += cal.get("totalContributions", 0)
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    d_str = day["date"]
                    c_cnt = day.get("contributionCount", 0)
                    day_map[d_str] = day_map.get(d_str, 0) + c_cnt

        current_streak, longest_streak = calculate_streaks_from_day_map(day_map)

    elif "contributionsCollection" in data:
        cal = data["contributionsCollection"]["contributionCalendar"]
        total_contributions = cal["totalContributions"]
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                d_str = day["date"]
                c_cnt = day.get("contributionCount", 0)
                day_map[d_str] = day_map.get(d_str, 0) + c_cnt

        current_streak, longest_streak = calculate_streaks_from_day_map(day_map)

    elif "daily_events" in data and data["daily_events"]:
        total_contributions = data.get("total_contributions", 0)
        day_map = data["daily_events"]
        current_streak, longest_streak = calculate_streaks_from_day_map(day_map)
    else:
        total_contributions = data.get("total_contributions", 0)
        current_streak = 0
        longest_streak = 0

    tot_str = f"{total_contributions:,}" if isinstance(total_contributions, int) else str(total_contributions)

    svg = f"""<svg width="450" height="100" viewBox="0 0 450 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .header {{ font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['subtext']}; }}
    .val {{ font: 700 20px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['title']}; }}
    .border {{ stroke: {THEME['border']}; stroke-width: 1; }}
    .bg {{ fill: {THEME['bg']}; rx: 10px; }}
    .divider {{ stroke: {THEME['border']}; stroke-width: 1; }}
  </style>
  <rect x="1" y="1" width="448" height="98" rx="8" class="bg border"/>

  <!-- Total -->
  <g transform="translate(20, 25)">
    <text x="60" y="15" text-anchor="middle" class="header">Total Contributions</text>
    <text x="60" y="48" text-anchor="middle" class="val">{tot_str}</text>
  </g>

  <line x1="150" y1="20" x2="150" y2="80" class="divider" />

  <!-- Current Streak -->
  <g transform="translate(165, 25)">
    <text x="60" y="15" text-anchor="middle" class="header">Current Streak</text>
    <text x="60" y="48" text-anchor="middle" class="val" fill="{THEME['green']}">{current_streak} days</text>
  </g>

  <line x1="295" y1="20" x2="295" y2="80" class="divider" />

  <!-- Longest Streak -->
  <g transform="translate(310, 25)">
    <text x="60" y="15" text-anchor="middle" class="header">Longest Streak</text>
    <text x="60" y="48" text-anchor="middle" class="val">{longest_streak} days</text>
  </g>
</svg>"""
    return svg


def get_month_range(start_ym, end_ym):
    start_y, start_m = map(int, start_ym.split("-"))
    end_y, end_m = map(int, end_ym.split("-"))
    months = []
    cur_y, cur_m = start_y, start_m
    while (cur_y < end_y) or (cur_y == end_y and cur_m <= end_m):
        months.append(f"{cur_y:04d}-{cur_m:02d}")
        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1
    return months


def generate_activity_graph_svg(data):
    # Overall monthly / yearly contribution activity graph
    month_counts = {}

    if "yearlyContributions" in data:
        for key in sorted(data["yearlyContributions"].keys()):
            yc = data["yearlyContributions"][key]
            if not yc:
                continue
            cal = yc.get("contributionCalendar", {})
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    m_str = day["date"][:7]  # YYYY-MM
                    month_counts[m_str] = month_counts.get(m_str, 0) + day.get("contributionCount", 0)
    elif "contributionsCollection" in data:
        cal = data["contributionsCollection"]["contributionCalendar"]
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                m_str = day["date"][:7]
                month_counts[m_str] = month_counts.get(m_str, 0) + day.get("contributionCount", 0)
    elif "daily_events" in data and data["daily_events"]:
        for d_str, count in data["daily_events"].items():
            m_str = d_str[:7]
            month_counts[m_str] = month_counts.get(m_str, 0) + count

    today_dt = datetime.now(timezone.utc)
    today_ym = today_dt.strftime("%Y-%m")

    if not month_counts:
        # Default 12 months ending at current month
        end_ym = today_ym
        end_y, end_m = map(int, end_ym.split("-"))
        start_y = end_y - 1 if end_m == 12 else end_y - 1
        start_m = 1 if end_m == 12 else end_m + 1
        start_ym = f"{start_y:04d}-{start_m:02d}"
        for m in get_month_range(start_ym, end_ym):
            month_counts[m] = 0
    else:
        sorted_keys = sorted(month_counts.keys())
        end_ym = sorted_keys[-1]
        if len(sorted_keys) == 1:
            end_y, end_m = map(int, end_ym.split("-"))
            start_y = end_y - 1
            start_m = end_m
            start_ym = f"{start_y:04d}-{start_m:02d}"
        else:
            start_ym = sorted_keys[0]

        all_months = get_month_range(start_ym, end_ym)
        for m in all_months:
            month_counts[m] = month_counts.get(m, 0)

    sorted_months = sorted(month_counts.keys())
    counts = [month_counts[m] for m in sorted_months]

    max_c = max(counts) if max(counts) > 0 else 1

    width = 880
    height = 150
    padding_x = 30
    padding_y = 25
    graph_w = width - (padding_x * 2)
    graph_h = height - (padding_y * 2)

    step = graph_w / max(1, len(counts) - 1)

    points = []
    for i, val in enumerate(counts):
        x = padding_x + (i * step)
        y = (height - padding_y) - ((val / max_c) * graph_h)
        points.append((x, y))

    if len(points) == 1:
        path_d = f"M {points[0][0]:.1f},{points[0][1]:.1f} L {points[0][0] + graph_w:.1f},{points[0][1]:.1f}"
    else:
        path_d = f"M {points[0][0]:.1f},{points[0][1]:.1f}"
        for x, y in points[1:]:
            path_d += f" L {x:.1f},{y:.1f}"

    area_d = path_d + f" L {points[-1][0]:.1f},{height - padding_y} L {padding_x},{height - padding_y} Z"

    start_label = sorted_months[0] if sorted_months else ""
    end_label = sorted_months[-1] if sorted_months else ""

    svg = f"""<svg width="880" height="170" viewBox="0 0 880 170" fill="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .header {{ font: 600 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['title']}; }}
    .sub {{ font: 400 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: {THEME['subtext']}; }}
    .border {{ stroke: {THEME['border']}; stroke-width: 1; }}
    .bg {{ fill: {THEME['bg']}; rx: 10px; }}
    .line {{ stroke: {THEME['line']}; stroke-width: 2; stroke-linecap: round; fill: none; }}
    .area {{ fill: url(#gradient); opacity: 0.4; }}
  </style>
  <defs>
    <linearGradient id="gradient" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{THEME['line']}" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="{THEME['line']}" stop-opacity="0.05"/>
    </linearGradient>
  </defs>

  <rect x="1" y="1" width="878" height="168" rx="8" class="bg border"/>
  <text x="30" y="25" class="header">Overall Contribution Activity ({start_label} to {end_label})</text>

  <path d="{area_d}" class="area" />
  <path d="{path_d}" class="line" />
</svg>"""
    return svg


def main():
    token = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if token:
        print("Fetching data using GraphQL API...")
        try:
            data = fetch_data_graphql(token)
        except GraphQLError as e:
            # Keep the last good SVGs instead of committing a card full of zeros.
            print(f"GraphQL fetch failed, leaving existing stats untouched: {e}")
            sys.exit(1)
    else:
        print("No token set, fetching data using REST API fallback...")
        data = fetch_data_rest()

    os.makedirs("assets", exist_ok=True)

    print("Generating assets/github-stats.svg...")
    with open("assets/github-stats.svg", "w", encoding="utf-8") as f:
        f.write(generate_stats_svg(data))

    print("Generating assets/top-langs.svg...")
    with open("assets/top-langs.svg", "w", encoding="utf-8") as f:
        f.write(generate_top_langs_svg(data))

    print("Generating assets/streak-stats.svg...")
    with open("assets/streak-stats.svg", "w", encoding="utf-8") as f:
        f.write(generate_streak_svg(data))

    print("Generating assets/activity-graph.svg...")
    with open("assets/activity-graph.svg", "w", encoding="utf-8") as f:
        f.write(generate_activity_graph_svg(data))

    print("All SVGs generated successfully!")


if __name__ == "__main__":
    main()
