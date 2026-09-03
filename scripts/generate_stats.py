#!/usr/bin/env python3
import json
import os
import sys
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


def fetch_data_graphql(token):
    # First query basic user details and creation date
    user_query = """
    {
      user(login: "%s") {
        name
        login
        createdAt
        followers { totalCount }
        following { totalCount }
        starredRepositories { totalCount }
        repositories(first: 100, ownerAffiliations: OWNER) {
          totalCount
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
    """ % USERNAME

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": user_query}).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Authorization": f"bearer {token}",
        },
    )
    with urllib.request.urlopen(req) as res:
        user_data = json.loads(res.read().decode())
        if "data" not in user_data or not user_data["data"]["user"]:
            return None
        user = user_data["data"]["user"]

    created_at = user.get("createdAt", "2016-01-01T00:00:00Z")
    start_year = int(created_at[:4])
    current_year = datetime.now(timezone.utc).year

    # Query contributionsCollection for all years from account creation to present
    year_queries = []
    for year in range(start_year, current_year + 1):
        from_date = f"{year}-01-01T00:00:00Z"
        to_date = f"{year}-12-31T23:59:59Z"
        year_queries.append(f"""
        year_{year}: contributionsCollection(from: "{from_date}", to: "{to_date}") {{
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalRepositoryContributions
          totalCodeReviewContributions
          contributionCalendar {{
            totalContributions
            weeks {{
              contributionDays {{
                contributionCount
                date
              }}
            }}
          }}
        }}
        """)

    multi_year_query = """
    {
      user(login: "%s") {
        %s
      }
    }
    """ % (USERNAME, "\n".join(year_queries))

    req2 = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": multi_year_query}).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Authorization": f"bearer {token}",
        },
    )
    with urllib.request.urlopen(req2) as res2:
        year_data = json.loads(res2.read().decode())
        if "data" in year_data and year_data["data"]["user"]:
            user["yearlyContributions"] = year_data["data"]["user"]

    return user


def fetch_data_rest():
    # Fallback using REST API
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

    # Search API exact queries
    commits_data = get_json(f"https://api.github.com/search/commits?q=author:{USERNAME}")
    prs_data = get_json(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:pr")
    issues_data = get_json(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:issue")

    commits = commits_data.get("total_count", 0)
    prs = prs_data.get("total_count", 0)
    issues = issues_data.get("total_count", 0)
    total_contributions = commits + prs + issues

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
    }


def generate_stats_svg(data):
    if "yearlyContributions" in data:  # GraphQL multi-year
        total_repos = data["repositories"]["totalCount"]
        total_stars = sum(r["stargazerCount"] for r in data["repositories"]["nodes"])
        total_forks = sum(r["forkCount"] for r in data["repositories"]["nodes"])
        followers = data["followers"]["totalCount"]

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

    elif "repositories" in data:  # GraphQL single year fallback
        total_repos = data["repositories"]["totalCount"]
        total_stars = sum(r["stargazerCount"] for r in data["repositories"]["nodes"])
        total_forks = sum(r["forkCount"] for r in data["repositories"]["nodes"])
        followers = data["followers"]["totalCount"]
        commits = data["contributionsCollection"]["totalCommitContributions"]
        prs = data["contributionsCollection"]["totalPullRequestContributions"]
        issues = data["contributionsCollection"]["totalIssueContributions"]
        contributions = data["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    else:  # REST fallback
        total_repos = data["user_info"].get("public_repos", 0)
        total_stars = data["total_stars"]
        total_forks = data["total_forks"]
        followers = data["user_info"].get("followers", 0)
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
    if "repositories" in data:  # GraphQL
        for repo in data["repositories"]["nodes"]:
            if repo.get("languages") and repo["languages"].get("edges"):
                for edge in repo["languages"]["edges"]:
                    l_name = edge["node"]["name"]
                    l_size = edge["size"]
                    langs[l_name] = langs.get(l_name, 0) + l_size
    else:  # REST
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


def generate_streak_svg(data):
    current_streak = 0
    longest_streak = 0
    total_contributions = 0

    all_days = []
    if "yearlyContributions" in data:  # GraphQL multi-year
        for key in sorted(data["yearlyContributions"].keys()):
            yc = data["yearlyContributions"][key]
            if not yc:
                continue
            cal = yc.get("contributionCalendar", {})
            total_contributions += cal.get("totalContributions", 0)
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    all_days.append(day)
    elif "contributionsCollection" in data:
        cal = data["contributionsCollection"]["contributionCalendar"]
        total_contributions = cal["totalContributions"]
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                all_days.append(day)

    if all_days:
        all_days.sort(key=lambda x: x["date"])

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yest_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        temp_streak = 0
        max_s = 0
        for d in all_days:
            if d["contributionCount"] > 0:
                temp_streak += 1
                if temp_streak > max_s:
                    max_s = temp_streak
            else:
                temp_streak = 0

        longest_streak = max_s

        curr = 0
        for d in reversed(all_days):
            if d["contributionCount"] > 0:
                curr += 1
            else:
                if d["date"] in (today_str, yest_str):
                    continue
                else:
                    break
        current_streak = curr
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


def generate_activity_graph_svg(data):
    counts = []
    all_days = []
    if "yearlyContributions" in data:
        for key in sorted(data["yearlyContributions"].keys()):
            yc = data["yearlyContributions"][key]
            if not yc:
                continue
            cal = yc.get("contributionCalendar", {})
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    all_days.append(day)
        all_days.sort(key=lambda x: x["date"])
        counts = [d["contributionCount"] for d in all_days]
    elif "contributionsCollection" in data:
        cal = data["contributionsCollection"]["contributionCalendar"]
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                counts.append(day["contributionCount"])
    else:
        import math
        counts = [int(3 + 3 * math.sin(i / 5)) for i in range(120)]

    counts = counts[-120:] if len(counts) >= 120 else counts
    if not counts:
        counts = [0] * 120

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

    path_d = f"M {points[0][0]},{points[0][1]}"
    for x, y in points[1:]:
        path_d += f" L {x:.1f},{y:.1f}"

    area_d = path_d + f" L {points[-1][0]:.1f},{height - padding_y} L {padding_x},{height - padding_y} Z"

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
  <text x="30" y="25" class="header">Contribution Activity (Last 4 Months)</text>

  <path d="{area_d}" class="area" />
  <path d="{path_d}" class="line" />
</svg>"""
    return svg


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    data = None
    if token:
        try:
            print("Fetching data using GraphQL API...")
            data = fetch_data_graphql(token)
        except Exception as e:
            print(f"GraphQL fetch failed: {e}")

    if not data:
        print("Fetching data using REST API fallback...")
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
