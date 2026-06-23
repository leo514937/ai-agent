'use client';

import React from 'react';

export default function ProfilePage() {
  const user = {
    nickname: '小鱼同学',
    phone: '13686869696',
    avatar: 'U', // First letter
    city: '杭州',
    introduce: '一棵开花的树，爱旅行，爱美食。',
    fans: 100,
    followee: 20,
    credits: 1000,
    gender: '男',
    birthday: '1995-05-20',
  };

  return (
    <div className="flex flex-col gap-8">
      {/* Profile Card */}
      <section className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm">
        <div className="flex flex-col sm:flex-row items-center gap-6">
          {/* Avatar */}
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white font-extrabold text-3xl shadow-theme-md">
            {user.avatar}
          </div>
          
          {/* Main Info */}
          <div className="flex-1 text-center sm:text-left">
            <h3 className="text-lg font-black text-themeText-main tracking-tight">{user.nickname}</h3>
            <p className="text-xs text-themeText-muted font-semibold mt-1">📱 绑定手机：{user.phone}</p>
            <p className="text-xs text-themeText-light italic mt-2">“ {user.introduce} ”</p>
          </div>

          {/* Action buttons */}
          <button className="px-5 py-2.5 rounded-theme-md text-xs font-bold text-white bg-primary hover:bg-primary-hover shadow-theme-sm transition-all active:scale-95">
            编辑个人资料
          </button>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-3 gap-4 border-t border-themeBorder mt-6 pt-6 text-center">
          <div className="flex flex-col">
            <span className="text-lg font-black text-themeText-main">{user.followee}</span>
            <span className="text-[10px] text-themeText-light font-bold">关注数</span>
          </div>
          <div className="border-x border-themeBorder flex flex-col">
            <span className="text-lg font-black text-themeText-main">{user.fans}</span>
            <span className="text-[10px] text-themeText-light font-bold">粉丝数</span>
          </div>
          <div className="flex flex-col">
            <span className="text-lg font-black text-themeText-main">{user.credits}</span>
            <span className="text-[10px] text-themeText-light font-bold">积分额</span>
          </div>
        </div>
      </section>

      {/* Details List */}
      <section className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm flex flex-col gap-5">
        <h4 className="font-extrabold text-sm text-themeText-main border-b border-themeBorder pb-3">
          📋 详细账号信息
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-bold text-themeText-muted">
          <div className="flex justify-between items-center p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
            <span>所在城市</span>
            <span className="text-themeText-main font-extrabold">{user.city}</span>
          </div>
          <div className="flex justify-between items-center p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
            <span>账号性别</span>
            <span className="text-themeText-main font-extrabold">{user.gender}</span>
          </div>
          <div className="flex justify-between items-center p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
            <span>出生日期</span>
            <span className="text-themeText-main font-extrabold">{user.birthday}</span>
          </div>
          <div className="flex justify-between items-center p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
            <span>当前定位</span>
            <span className="text-themeText-main font-extrabold">北京邮电大学海淀校区</span>
          </div>
        </div>
      </section>
    </div>
  );
}
