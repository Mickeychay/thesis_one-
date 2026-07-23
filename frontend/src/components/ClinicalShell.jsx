import { useEffect, useMemo, useRef, useState } from 'react';

const runtimeTone = {
  ready: {
    dot: 'bg-emerald-500',
    label: 'ระบบพร้อม',
    text: 'text-emerald-700 dark:text-emerald-300',
  },
  degraded: {
    dot: 'bg-amber-500',
    label: 'ระบบจำกัด',
    text: 'text-amber-700 dark:text-amber-300',
  },
  loading: {
    dot: 'bg-sky-500 animate-pulse',
    label: 'กำลังเตรียมระบบ',
    text: 'text-sky-700 dark:text-sky-300',
  },
  error: {
    dot: 'bg-red-500',
    label: 'ระบบขัดข้อง',
    text: 'text-red-700 dark:text-red-300',
  },
};

function BrandMark({ compact = false }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#0d2734] text-white shadow-sm shadow-slate-950/10">
        <span aria-hidden="true" className="material-symbols-outlined text-[22px]">health_and_safety</span>
      </div>
      <div className={compact ? 'min-w-0' : ''}>
        <div className="truncate font-headline text-base font-bold text-slate-950 dark:text-white">{compact ? 'H2L Clinical' : 'H2L Clinical Social Work'}</div>
        {!compact && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Health decision support</div>}
      </div>
    </div>
  );
}

function Navigation({ activeTab, navItems, onNavigate }) {
  const groups = useMemo(() => {
    const collected = [];
    navItems.forEach((item) => {
      let group = collected.find((entry) => entry.id === item.group);
      if (!group) {
        group = { id: item.group, label: item.groupLabel, items: [] };
        collected.push(group);
      }
      group.items.push(item);
    });
    return collected;
  }, [navItems]);

  return (
    <nav aria-label="เมนูหลัก" className="space-y-6">
      {groups.map((group) => (
        <div key={group.id}>
          <div className="mb-2 px-3 text-xs font-semibold text-slate-400 dark:text-slate-500">{group.label}</div>
          <div className="space-y-1">
            {group.items.map((item) => {
              const active = activeTab === item.id;
              return (
                <button
                  aria-current={active ? 'page' : undefined}
                  className={`group flex min-h-12 w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${
                    active
                      ? 'bg-white text-[#0f766e] shadow-sm shadow-slate-900/5 dark:bg-slate-800 dark:text-teal-300'
                      : 'text-slate-600 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white'
                  }`}
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  type="button"
                >
                  <span aria-hidden="true" className={`material-symbols-outlined shrink-0 text-[21px] ${active ? 'text-teal-600 dark:text-teal-300' : 'text-slate-400 group-hover:text-slate-700 dark:group-hover:text-slate-200'}`}>
                    {item.icon}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{item.label}</span>
                    <span className="mt-0.5 block truncate text-xs text-slate-400 dark:text-slate-500">{item.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

export default function ClinicalShell({
  activeTab,
  caseStatusLabel,
  caseStatusTone = 'neutral',
  children,
  navItems,
  onNavigate,
  onToggleTheme,
  onVerifyRuntime,
  runtimeStatus,
  theme,
}) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileMenuButtonRef = useRef(null);
  const mobileDrawerRef = useRef(null);
  const mobileCloseButtonRef = useRef(null);
  const activeItem = navItems.find((item) => item.id === activeTab) || navItems[0];
  const runtime = runtimeTone[runtimeStatus?.status] || runtimeTone.error;
  const handleNavigate = (itemId) => {
    setMobileNavOpen(false);
    onNavigate(itemId);
    window.requestAnimationFrame(() => document.getElementById('main-content')?.focus());
  };

  useEffect(() => {
    if (!mobileNavOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    mobileCloseButtonRef.current?.focus();
    const handleDialogKeyDown = (event) => {
      if (event.key === 'Escape') {
        setMobileNavOpen(false);
        window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...(mobileDrawerRef.current?.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleDialogKeyDown);
    };
  }, [mobileNavOpen]);

  return (
    <div className="min-h-dvh bg-background text-on-background">
      <a className="fixed left-4 top-3 z-[80] -translate-y-20 rounded-lg bg-[#0d2734] px-4 py-2 text-sm font-semibold text-white transition-transform focus:translate-y-0" href="#main-content">
        ข้ามไปยังเนื้อหาหลัก
      </a>

      <aside className="fixed inset-y-0 left-0 z-50 hidden w-64 flex-col border-r border-slate-200/70 bg-slate-50 px-4 py-5 dark:border-slate-800 dark:bg-[#0d131f] lg:flex">
        <div className="px-2">
          <BrandMark />
        </div>
        <div className="mt-8 flex-1 overflow-y-auto pr-1">
          <Navigation activeTab={activeTab} navItems={navItems} onNavigate={handleNavigate} />
        </div>
        <div className="mt-5 border-t border-slate-200/70 pt-4 dark:border-slate-800">
          <button
            className="flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-[#0d2734] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#16394a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
            onClick={onVerifyRuntime}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[20px]">monitor_heart</span>
            ตรวจสอบระบบ
          </button>
          <div className="mt-3 flex items-start gap-2 px-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
            <span aria-hidden="true" className="material-symbols-outlined mt-0.5 text-[17px] text-teal-600 dark:text-teal-300">shield_person</span>
            <span>ใช้ข้อมูลที่ลดการระบุตัวบุคคล และให้ผู้เชี่ยวชาญทบทวนก่อนตัดสินใจเสมอ</span>
          </div>
        </div>
      </aside>

      <header className="fixed inset-x-0 top-0 z-40 border-b border-slate-200/70 bg-white/92 backdrop-blur-xl dark:border-slate-800 dark:bg-[#0d131f]/92 lg:left-64">
        <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              aria-label="เปิดเมนูหลัก"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800 lg:hidden"
              onClick={() => setMobileNavOpen(true)}
              ref={mobileMenuButtonRef}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-outlined">menu</span>
            </button>
            <div className="lg:hidden">
              <BrandMark compact />
            </div>
            <div className="hidden min-w-0 lg:block">
              <div className="truncate font-headline text-lg font-bold text-slate-950 dark:text-white">{activeItem.label}</div>
              <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">{activeItem.description}</div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button
              aria-label={`สถานะระบบ: ${runtime.label}. กดเพื่อตรวจสอบอีกครั้ง`}
              className="flex min-h-11 items-center gap-2 rounded-lg px-2.5 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800 sm:px-3"
              onClick={onVerifyRuntime}
              type="button"
            >
              <span className={`h-2.5 w-2.5 rounded-full ${runtime.dot}`} />
              <span className={`hidden md:inline ${runtime.text}`}>{runtime.label}</span>
            </button>
            <button
              aria-label={theme === 'dark' ? 'เปลี่ยนเป็นโหมดสว่าง' : 'เปลี่ยนเป็นโหมดมืด'}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800"
              onClick={onToggleTheme}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-outlined">{theme === 'dark' ? 'light_mode' : 'dark_mode'}</span>
            </button>
            <div className={`hidden rounded-lg px-3 py-2 text-xs font-semibold sm:block ${
              caseStatusTone === 'live'
                ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200'
                : caseStatusTone === 'warning'
                  ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200'
                  : caseStatusTone === 'error'
                    ? 'bg-red-50 text-red-800 dark:bg-red-950/50 dark:text-red-200'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
            }`}>
              {caseStatusLabel}
            </div>
          </div>
        </div>
      </header>

      {mobileNavOpen && <div aria-label="เมนูหลัก" aria-modal="true" className="fixed inset-0 z-[70] lg:hidden" role="dialog">
        <button
          aria-label="ปิดเมนูหลัก"
          className="absolute inset-0 bg-slate-950/50"
          onClick={() => {
            setMobileNavOpen(false);
            window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
          }}
          tabIndex={-1}
          type="button"
        />
        <aside className="page-enter absolute inset-y-0 left-0 flex w-[min(88vw,320px)] overscroll-contain flex-col bg-slate-50 p-4 shadow-2xl dark:bg-[#0d131f]" ref={mobileDrawerRef}>
          <div className="flex items-center justify-between gap-3 px-2 py-1">
            <BrandMark />
            <button
              aria-label="ปิดเมนู"
              className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-600 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800"
              onClick={() => {
                setMobileNavOpen(false);
                window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
              }}
              ref={mobileCloseButtonRef}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-outlined">close</span>
            </button>
          </div>
          <div className="mt-7 flex-1 overflow-y-auto">
            <Navigation activeTab={activeTab} navItems={navItems} onNavigate={handleNavigate} />
          </div>
          <button
            className="mt-4 flex min-h-12 items-center justify-center gap-2 rounded-lg bg-[#0d2734] px-4 py-3 text-sm font-semibold text-white"
            onClick={onVerifyRuntime}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[20px]">monitor_heart</span>
            ตรวจสอบระบบ
          </button>
        </aside>
      </div>}

      <main className="min-h-dvh px-4 pb-16 pt-20 sm:px-6 lg:ml-64 lg:px-8" id="main-content" tabIndex="-1">
        <div className="mx-auto w-full max-w-[1600px]">{children}</div>
      </main>
    </div>
  );
}
