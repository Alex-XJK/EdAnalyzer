#!/usr/bin/env python3
"""
Ed Discussion SLO Analysis Tool

This tool analyzes Ed Discussion JSON data to compute Service Level Objectives (SLO)
for answering student questions.

Author:
    Alex Jiakai Xu <jiakai.xu@columbia.edu>

Usage:
    python ed_slo_analyzer.py <json_file> [options]

Options:
    --mode {details|week|overall}  Analysis mode (default: overall)
    --categorize                   Show breakdown by category, only for week and overall modes
    --count-unconfirmed           Count unconfirmed student answers as resolved (default: False)
    --skip-weekends               Skip threads posted on weekends in statistical modes (default: False)
    --help                        Show this help message
"""

import argparse
import json
import sys
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from statistics import mean, median
from typing import List, Optional, Dict, Any


class ThreadStatus(Enum):
    """Enumeration of thread status types."""
    RESOLVED = "Resolved"  # Answered by admin/staff
    ENDORSED = "Endorsed"  # Student answer with endorsement
    UNCONFIRMED = "Unconfirmed"  # Student answer without endorsement
    PENDING = "Pending"  # No answers


@dataclass
class ThreadEntry:
    """Represents a question thread with relevant SLO data."""
    id: int
    category: str
    subcategory: str
    subsubcategory: str
    created_at: datetime
    status: ThreadStatus
    first_answer_at: Optional[datetime]
    response_delay: Optional[timedelta]

    def is_effectively_answered(self, count_unconfirmed: bool = False) -> bool:
        """
        Check if the question is effectively answered based on status.

        Args:
            count_unconfirmed: Whether to count unconfirmed answers as resolved

        Returns:
            True if the question should be considered answered
        """
        if self.status in [ThreadStatus.RESOLVED, ThreadStatus.ENDORSED]:
            return True
        elif self.status == ThreadStatus.UNCONFIRMED and count_unconfirmed:
            return True
        return False

    @property
    def is_weekend_post(self) -> bool:
        """Check if the thread was posted on weekend (Saturday=5, Sunday=6)."""
        return self.created_at.weekday() >= 5

    @property
    def response_delay_hours(self) -> Optional[float]:
        """Get response delay in hours."""
        if self.response_delay:
            return self.response_delay.total_seconds() / 3600
        return None

    @property
    def category_path(self) -> str:
        """Get the full category path."""
        parts = [self.category]
        if self.subcategory:
            parts.append(self.subcategory)
        if self.subsubcategory:
            parts.append(self.subsubcategory)
        return "-".join(parts)

    def __str__(self) -> str:
        delay_info = f"{self.response_delay_hours:.2f}h" if self.first_answer_at else "N/A"
        weekend_annotation = "(W)" if self.is_weekend_post else ""
        status_info = f"[{self.status.value}]"
        return f"#{self.id:3d} >> {self.category_path:<30} : {delay_info:<8} {weekend_annotation:<4} {status_info}"


class EdAnalyzer:
    """
    Main analyzer class for Ed Discussion SLO metrics.
    """

    # New York timezone for all timestamp conversions
    DEFAULT_TZ = zoneinfo.ZoneInfo("America/New_York")

    def __init__(self, json_file: str):
        """
        Initialize the analyzer with a JSON file.
        :param json_file: Path to the Ed Discussion JSON file.
        """
        self.threads = self._load_and_parse(json_file)

    def _load_and_parse(self, json_file: str) -> List[ThreadEntry]:
        """
        Load and parse the JSON file into ThreadEntry objects.
        """
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"Error: File '{json_file}' not found.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON format - {e}")
            sys.exit(1)

        threads = []
        for item in data:
            if item.get('type') == 'question':
                thread = self._parse_thread(item)
                if thread:
                    threads.append(thread)

        return threads

    @staticmethod
    def _parse_thread(item: Dict[str, Any]) -> Optional[ThreadEntry]:
        """
        Parse a single thread item into a ThreadEntry object.
        """
        try:
            # Parse created timestamp and convert to NY time
            created_at_original = datetime.fromisoformat(item['created_at'])
            created_at = created_at_original.astimezone(EdAnalyzer.DEFAULT_TZ)

            # Determine status and answer timestamp based on chronological order
            answers = item.get('answers', [])
            status, first_answer_at, response_delay = EdAnalyzer._determine_thread_status(
                answers, created_at
            )

            return ThreadEntry(
                id=item['number'],
                category=item.get('category', ''),
                subcategory=item.get('subcategory', ''),
                subsubcategory=item.get('subsubcategory', ''),
                created_at=created_at,
                status=status,
                first_answer_at=first_answer_at,
                response_delay=response_delay
            )

        except (KeyError, ValueError) as e:
            print(f"Warning: Skipping malformed thread - {e}")
            return None

    @staticmethod
    def _determine_thread_status(answers: List[Dict[str, Any]], created_at: datetime) -> tuple:
        """
        Determine the thread status based on answers in chronological order.

        Returns:
            Tuple of (status, first_qualifying_answer_at, response_delay)
        """
        if not answers:
            return ThreadStatus.PENDING, None, None

        # Find the first qualifying answer (staff/admin or endorsed student answer)
        first_qualifying_answer = None
        final_status = ThreadStatus.UNCONFIRMED  # Default if only unconfirmed answers exist

        for answer in answers:
            user_role = answer.get('user', {}).get('role', '')
            is_endorsed = answer.get('endorsed', False)

            # Check if this answer qualifies (staff/admin or endorsed)
            if user_role in ['admin', 'staff'] or is_endorsed:
                first_qualifying_answer = answer
                # Determine final status based on the presence of staff/admin answers
                has_staff_answer = any(
                    ans.get('user', {}).get('role', '') in ['admin', 'staff']
                    for ans in answers
                )
                final_status = ThreadStatus.RESOLVED if has_staff_answer else ThreadStatus.ENDORSED
                break

        if first_qualifying_answer:
            answer_time_original = datetime.fromisoformat(first_qualifying_answer['created_at'])
            answer_time = answer_time_original.astimezone(EdAnalyzer.DEFAULT_TZ)
            return (
                final_status,
                answer_time,
                answer_time - created_at
            )
        else:
            # Only unconfirmed answers exist, use first answer
            first_answer = answers[0]
            answer_time_original = datetime.fromisoformat(first_answer['created_at'])
            answer_time = answer_time_original.astimezone(EdAnalyzer.DEFAULT_TZ)
            return (
                ThreadStatus.UNCONFIRMED,
                answer_time,
                answer_time - created_at
            )

    @staticmethod
    def _filter_threads(threads: List[ThreadEntry], skip_weekends: bool = False) -> List[ThreadEntry]:
        """
        Filter threads based on criteria.

        Args:
            threads: List of threads to filter
            skip_weekends: Whether to skip threads posted on weekends

        Returns:
            Filtered list of threads
        """
        if not skip_weekends:
            return threads

        return [t for t in threads if not t.is_weekend_post]

    def show_details(self) -> None:
        """
        Show detailed information for all question threads.
        """
        print("=== Question Thread Details ===\n")

        for thread in self.threads:
            print(thread)

        print(f"\nTotal questions analyzed: {len(self.threads)}")

    def show_week_stats(self, categorize: bool, count_unconfirmed: bool = False, skip_weekends: bool = False) -> None:
        """
        Show statistics for the last week.
        """
        # Use NY time for "now" and week calculation
        now = datetime.now(EdAnalyzer.DEFAULT_TZ)
        week_ago = now - timedelta(days=7)

        # Filter threads from last week
        week_threads = [
            t for t in self.threads
            if t.created_at >= week_ago
        ]

        # Apply weekend filtering
        filtered_threads = self._filter_threads(week_threads, skip_weekends)

        print("=== Last Week Statistics ===\n")
        if skip_weekends and len(filtered_threads) != len(week_threads):
            skipped_count = len(week_threads) - len(filtered_threads)
            print(f"Note: Skipped {skipped_count} weekend posts from analysis.")

        self._show_statistics(filtered_threads, "last week", count_unconfirmed)

        if categorize:
            self._show_category_breakdown(filtered_threads, count_unconfirmed)

    def show_overall_stats(self, categorize: bool, count_unconfirmed: bool = False,
                           skip_weekends: bool = False) -> None:
        """
        Show overall statistics for all threads.
        """
        # Apply weekend filtering
        filtered_threads = self._filter_threads(self.threads, skip_weekends)

        print("=== Overall Statistics ===\n")
        if skip_weekends and len(filtered_threads) != len(self.threads):
            skipped_count = len(self.threads) - len(filtered_threads)
            print(f"Note: Skipped {skipped_count} weekend posts from analysis.")

        self._show_statistics(filtered_threads, "overall", count_unconfirmed)

        if categorize:
            self._show_category_breakdown(filtered_threads, count_unconfirmed)

    @staticmethod
    def _show_statistics(threads: List[ThreadEntry], period: str, count_unconfirmed: bool = False) -> None:
        """
        Show statistics for a given set of threads.
        """
        if not threads:
            print(f"No questions found for {period}.")
            return

        # Status breakdown
        status_counts = {status: 0 for status in ThreadStatus}
        for thread in threads:
            status_counts[thread.status] += 1

        # Effectively answered threads
        answered_threads = [t for t in threads if t.is_effectively_answered(count_unconfirmed)]

        total_count = len(threads)
        answered_count = len(answered_threads)

        print(f"Period: {period.title()}")
        print(f"Total questions: {total_count}")
        print()
        print("Status Breakdown:")
        print(f"  Resolved (by staff/admin): {status_counts[ThreadStatus.RESOLVED]}")
        print(f"  Endorsed (student + endorsed): {status_counts[ThreadStatus.ENDORSED]}")
        print(f"  Unconfirmed (student only): {status_counts[ThreadStatus.UNCONFIRMED]}")
        print(f"  Pending (no answers): {status_counts[ThreadStatus.PENDING]}")
        print()

        unconfirmed_note = " (including unconfirmed)" if count_unconfirmed else ""
        print(f"Effectively answered{unconfirmed_note}: {answered_count} ({answered_count / total_count * 100:.1f}%)")

        if answered_threads:
            response_times = [t.response_delay_hours for t in answered_threads if t.response_delay_hours is not None]

            if response_times:
                print(f"\n--- Response Time Analysis ---")
                print(f"Average response time: {mean(response_times):.2f} hours")
                print(f"Median response time: {median(response_times):.2f} hours")
                print(f"Fastest response: {min(response_times):.2f} hours")
                print(f"Slowest response: {max(response_times):.2f} hours")

                # SLO metrics
                within_6h = sum(1 for t in response_times if t <= 6)
                within_24h = sum(1 for t in response_times if t <= 24)
                within_48h = sum(1 for t in response_times if t <= 48)

                print(f"\n--- SLO Metrics ---")
                print(f"Answered within 6 hours: {within_6h}/{answered_count} ({within_6h / answered_count * 100:.1f}%)")
                print(
                    f"Answered within 24 hours: {within_24h}/{answered_count} ({within_24h / answered_count * 100:.1f}%)")
                print(
                    f"Answered within 48 hours: {within_48h}/{answered_count} ({within_48h / answered_count * 100:.1f}%)")

    @staticmethod
    def _show_category_breakdown(threads: List[ThreadEntry], count_unconfirmed: bool = False) -> None:
        """
        Show breakdown by category.
        """
        category_stats = {}

        for thread in threads:
            category = thread.category_path
            if category not in category_stats:
                category_stats[category] = {
                    'total': 0,
                    'answered': 0,
                    'response_times': [],
                    'status_counts': {status: 0 for status in ThreadStatus}
                }

            category_stats[category]['total'] += 1
            category_stats[category]['status_counts'][thread.status] += 1

            if thread.is_effectively_answered(count_unconfirmed):
                category_stats[category]['answered'] += 1
                if thread.response_delay_hours is not None:
                    category_stats[category]['response_times'].append(thread.response_delay_hours)

        if category_stats:
            unconfirmed_note = " (including unconfirmed)" if count_unconfirmed else ""
            print(f"\n--- Category Breakdown{unconfirmed_note} ---")
            for category, stats in sorted(category_stats.items()):
                total = stats['total']
                answered = stats['answered']
                answer_rate = answered / total * 100 if total > 0 else 0

                avg_time = "N/A"
                if stats['response_times']:
                    avg_time = f"{mean(stats['response_times']):.2f}h"

                resolved = stats['status_counts'][ThreadStatus.RESOLVED]
                endorsed = stats['status_counts'][ThreadStatus.ENDORSED]
                unconfirmed = stats['status_counts'][ThreadStatus.UNCONFIRMED]
                pending = stats['status_counts'][ThreadStatus.PENDING]

                print(f"{category:<30}: {answered:3d}/{total:3d} ({answer_rate:.1f}%) - Avg: {avg_time}")
                print(f"{'':32}  [R:{resolved} E:{endorsed} U:{unconfirmed} P:{pending}]")


"""Main entry point for the CLI application."""
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Analyze Ed Discussion JSON data for SLO metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python ed_slo_analyzer.py data.json --mode details
    python ed_slo_analyzer.py data.json --mode week --categorize --skip-weekends
    python ed_slo_analyzer.py data.json --mode overall --count-unconfirmed
        """
    )

    parser.add_argument(
        'json_file',
        help='Path to the Ed Discussion JSON file'
    )

    parser.add_argument(
        '-m', '--mode',
        choices=['details', 'week', 'overall'],
        default='overall',
        help='Analysis mode: details (show all threads), week (last week stats), overall (all stats)'
    )

    parser.add_argument(
        '-c', '--categorize',
        action='store_true',
        default=False,
        help='Show breakdown by category (only for week and overall modes)'
    )

    parser.add_argument(
        '-u', '--count-unconfirmed',
        action='store_true',
        default=False,
        help='Count unconfirmed student answers as resolved (default: False)'
    )

    parser.add_argument(
        '-s', '--skip-weekends',
        action='store_true',
        default=False,
        help='Skip threads posted on weekends in statistical modes (default: False)'
    )

    args = parser.parse_args()

    try:
        analyzer = EdAnalyzer(args.json_file)

        if args.mode == 'details':
            analyzer.show_details()
        elif args.mode == 'week':
            analyzer.show_week_stats(
                categorize=args.categorize,
                count_unconfirmed=args.count_unconfirmed,
                skip_weekends=args.skip_weekends
            )
        else:  # overall
            analyzer.show_overall_stats(
                categorize=args.categorize,
                count_unconfirmed=args.count_unconfirmed,
                skip_weekends=args.skip_weekends
            )

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)