import React from 'react';

interface SkeletonProps {
  className?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({ className = '' }) => {
  return (
    <div
      className={`animate-pulse rounded bg-gray-200 dark:bg-zinc-700 ${className}`}
    />
  );
};

export default Skeleton;
