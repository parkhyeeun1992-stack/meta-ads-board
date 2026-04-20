import React from "react";

type MenuItem = {
  label: string;
  active?: boolean;
};

type FilterOption = {
  label: string;
  checked?: boolean;
};

type AdCard = {
  rank: number;
  title: string;
  hospital: string;
  date: string;
  views: string;
  avatar: string;
};

const menuItems: MenuItem[] = [
  { label: "메인 갤러리", active: true },
  { label: "내 보드" },
];

const filterOptions: FilterOption[] = [
  { label: "단일이미지" },
  { label: "영상" },
  { label: "캐러셀", checked: true },
];

const categories = [
  "라미네이트",
  "임플란트",
  "교정",
  "피부과",
  "안과",
  "리프팅",
  "제모",
  "성형외과",
  "가슴성형",
  "코성형",
];

const adCards: AdCard[] = [
  { rank: 1, title: "리프팅 집중 캠페인", hospital: "로운피부과", date: "2026.03.27", views: "12.4K views", avatar: "LP" },
  { rank: 2, title: "임플란트 시술 상세", hospital: "화이트치과", date: "2026.03.26", views: "10.8K views", avatar: "WD" },
  { rank: 3, title: "쌍꺼풀 자연유착 광고", hospital: "메이성형외과", date: "2026.03.26", views: "9.7K views", avatar: "MS" },
  { rank: 4, title: "백내장 상담 전환형", hospital: "밝은안과", date: "2026.03.25", views: "8.4K views", avatar: "BE" },
  { rank: 5, title: "프리미엄 라미네이트", hospital: "클리어치과", date: "2026.03.25", views: "7.9K views", avatar: "CL" },
  { rank: 6, title: "여성 제모 패키지", hospital: "샤인의원", date: "2026.03.24", views: "7.2K views", avatar: "SH" },
  { rank: 7, title: "코성형 리얼 후기형", hospital: "에이든성형외과", date: "2026.03.24", views: "6.8K views", avatar: "AD" },
  { rank: 8, title: "리쥬란 탄력 부스팅", hospital: "스킨랩의원", date: "2026.03.23", views: "6.3K views", avatar: "SL" },
  { rank: 9, title: "가슴성형 상담 유도", hospital: "비엘성형외과", date: "2026.03.22", views: "5.9K views", avatar: "BL" },
  { rank: 10, title: "남성 제모 전환형", hospital: "유앤아이의원", date: "2026.03.22", views: "5.4K views", avatar: "UI" },
];

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-slate-400">
      <path d="M7 3v3M17 3v3M4 9h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="4" y="5" width="16" height="15" rx="3" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-slate-400">
      <path d="M7 10l5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function RadioIcon({ checked }: { checked?: boolean }) {
  return (
    <span
      className={[
        "flex h-4 w-4 items-center justify-center rounded-full border transition",
        checked ? "border-[#3182F6]" : "border-slate-300",
      ].join(" ")}
    >
      <span className={["h-2 w-2 rounded-full", checked ? "bg-[#3182F6]" : "bg-transparent"].join(" ")} />
    </span>
  );
}

function RecommendedAdsDashboard() {
  return (
    <div className="min-h-screen bg-[#FCFCFD] text-slate-900">
      <aside className="fixed left-0 top-0 flex h-screen w-80 flex-col border-r border-slate-100 bg-white px-6 py-8">
        <div className="space-y-1">
          {menuItems.map((item) => (
            <button
              key={item.label}
              className={[
                "flex w-full items-center rounded-xl px-4 py-3 text-left text-sm transition",
                item.active
                  ? "bg-[#E8F3FF] font-semibold text-[#3182F6]"
                  : "text-[#4E5968] hover:bg-[#F2F4F6]",
              ].join(" ")}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="my-8 h-px bg-slate-100" />

        <div className="space-y-6">
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-800">필터</h2>
            <div className="space-y-2">
              <p className="text-sm text-[#4E5968]">날짜 범위</p>
              <button className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
                <span className="flex items-center gap-2">
                  <CalendarIcon />
                  <span>2026/03/01 - 2026/03/27</span>
                </span>
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-sm text-[#4E5968]">광고 유형</p>
            <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
              <button className="mb-2 flex w-full items-center justify-between px-1 py-1 text-left text-sm font-medium text-slate-700">
                <span>광고 유형</span>
                <ChevronDownIcon />
              </button>

              <div className="space-y-1">
                {filterOptions.map((option) => (
                  <button
                    key={option.label}
                    className="flex w-full items-center justify-between rounded-xl px-3 py-3 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    <span className={option.checked ? "font-medium text-[#3182F6]" : ""}>{option.label}</span>
                    <RadioIcon checked={option.checked} />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-auto pt-8">
          <button className="w-full rounded-xl bg-[#3182F6] px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#2272e5]">
            확인
          </button>
        </div>
      </aside>

      <main className="ml-80 min-h-screen px-10 py-10">
        <div className="mx-auto max-w-[1440px]">
          <header className="mb-8 text-center">
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">오늘의 AI 추천 광고</h1>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              {categories.map((category, index) => (
                <button
                  key={category}
                  className={[
                    "rounded-full px-4 py-2 text-sm transition",
                    index === 0
                      ? "bg-[#E8F3FF] font-semibold text-[#3182F6]"
                      : "border border-slate-200 bg-white text-[#4E5968] hover:bg-slate-50",
                  ].join(" ")}
                >
                  {category}
                </button>
              ))}
            </div>
          </header>

          <section className="grid grid-cols-5 gap-5">
            {adCards.map((card) => (
              <article
                key={card.rank}
                className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_8px_24px_rgba(15,23,42,0.04)]"
              >
                <div className="aspect-[4/3] w-full bg-gradient-to-br from-slate-100 via-slate-50 to-slate-200" />

                <div className="space-y-3 p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#E8F3FF] text-xs font-semibold text-[#3182F6]">
                      {card.avatar}
                    </div>

                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {card.rank}위 · {card.title}
                      </p>
                      <p className="mt-1 truncate text-xs text-[#6B7684]">{card.hospital}</p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs text-[#8B95A1]">
                    <span>{card.date}</span>
                    <span>{card.views}</span>
                  </div>

                  <button className="w-full rounded-xl bg-[#F2F4F6] px-3 py-2.5 text-sm font-medium text-[#333D4B] transition hover:bg-[#E5E8EB]">
                    상세 보기 및 AI 분석
                  </button>
                </div>
              </article>
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}

export default RecommendedAdsDashboard;
