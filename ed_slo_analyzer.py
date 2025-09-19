#!/usr/bin/env python3
"""
Ed Discussion SLO Analysis Tool

This tool analyzes Ed Discussion JSON data to compute Service Level Objectives (SLO)
for answering student questions.

Usage:
    python ed_slo_analyzer.py <json_file> [options]
    
Options:
    --mode {details|week|overall}  Analysis mode (default: overall)
    --categorize                   Show breakdown by category, only for week and overall modes
    --help                        Show this help message
"""

import json
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from statistics import mean, median


@dataclass
class ThreadEntry:
    """Represents a question thread with relevant SLO data."""
    id: int
    category: str
    subcategory: str
    subsubcategory: str
    created_at: datetime
    first_answer_at: Optional[datetime]
    response_delay: Optional[timedelta]
    
    @property
    def is_answered(self) -> bool:
        """Check if the question has been answered."""
        return self.first_answer_at is not None
    
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
        delay_info = f"{self.response_delay_hours:.2f}h" if self.is_answered else "N/A"
        return f"#{self.id:3d} >> {self.category_path:<30} : {delay_info}"


class EdAnalyzer:
    """
    Main analyzer class for Ed Discussion SLO metrics.
    """
    
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
            # Parse created timestamp
            created_at = datetime.fromisoformat(item['created_at'])
            
            # Parse first answer timestamp if exists
            first_answer_at = None
            response_delay = None
            
            answers = item.get('answers', [])
            if answers:
                first_answer_created = answers[0]['created_at']
                first_answer_at = datetime.fromisoformat(first_answer_created)
                response_delay = first_answer_at - created_at
            
            return ThreadEntry(
                id=item['number'],
                category=item.get('category', ''),
                subcategory=item.get('subcategory', ''),
                subsubcategory=item.get('subsubcategory', ''),
                created_at=created_at,
                first_answer_at=first_answer_at,
                response_delay=response_delay
            )
        
        except (KeyError, ValueError) as e:
            print(f"Warning: Skipping malformed thread - {e}")
            return None
    
    def show_details(self) -> None:
        """
        Show detailed information for all question threads.
        """
        print("=== Question Thread Details ===\n")
        
        for thread in self.threads:
            print(thread)
        
        print(f"\nTotal questions analyzed: {len(self.threads)}")
    
    def show_week_stats(self, categorize: bool) -> None:
        """
        Show statistics for the last week.
        """
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        
        # Filter threads from last week
        week_threads = [
            t for t in self.threads 
            if t.created_at >= week_ago.replace(tzinfo=t.created_at.tzinfo)
        ]
        
        print("=== Last Week Statistics ===\n")
        self._show_statistics(week_threads, "last week")

        if categorize:
            self._show_category_breakdown(week_threads)
    
    def show_overall_stats(self, categorize: bool) -> None:
        """
        Show overall statistics for all threads.
        """
        print("=== Overall Statistics ===\n")
        self._show_statistics(self.threads, "overall")

        if categorize:
            self._show_category_breakdown(self.threads)

    @staticmethod
    def _show_statistics(threads: List[ThreadEntry], period: str) -> None:
        """
        Show statistics for a given set of threads.
        """
        if not threads:
            print(f"No questions found for {period}.")
            return
        
        answered_threads = [t for t in threads if t.is_answered]

        total_count = len(threads)
        answered_count = len(answered_threads)

        print(f"Period: {period.title()}")
        print(f"Total questions: {total_count}")
        print(f"Answered questions: {answered_count} ({answered_count/total_count*100:.1f}%)")

        if answered_threads:
            response_times = [t.response_delay_hours for t in answered_threads]
            
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
            print(f"Answered within 6 hour: {within_6h}/{answered_count} ({within_6h/answered_count*100:.1f}%)")
            print(f"Answered within 24 hours: {within_24h}/{answered_count} ({within_24h/answered_count*100:.1f}%)")
            print(f"Answered within 48 hours: {within_48h}/{answered_count} ({within_48h/answered_count*100:.1f}%)")
    
    @staticmethod
    def _show_category_breakdown(threads: List[ThreadEntry]) -> None:
        """
        Show breakdown by category.
        """
        category_stats = {}
        
        for thread in threads:
            category = thread.category_path
            if category not in category_stats:
                category_stats[category] = {'total': 0, 'answered': 0, 'response_times': []}
            
            category_stats[category]['total'] += 1
            if thread.is_answered:
                category_stats[category]['answered'] += 1
                category_stats[category]['response_times'].append(thread.response_delay_hours)
        
        if category_stats:
            print(f"\n--- Category Breakdown ---")
            for category, stats in sorted(category_stats.items()):
                total = stats['total']
                answered = stats['answered']
                answer_rate = answered / total * 100 if total > 0 else 0
                
                avg_time = "N/A"
                if stats['response_times']:
                    avg_time = f"{mean(stats['response_times']):.2f}h"
                
                print(f"{category:<30}: {answered:3d}/{total:3d} ({answer_rate:.1f}%) - Avg: {avg_time}")


"""Main entry point for the CLI application."""
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Analyze Ed Discussion JSON data for SLO metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python ed_slo_analyzer.py data.json --mode details
    python ed_slo_analyzer.py data.json --mode week --categorize
    python ed_slo_analyzer.py data.json --mode overall
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
    
    args = parser.parse_args()
    
    try:
        analyzer = EdAnalyzer(args.json_file)
        
        if args.mode == 'details':
            analyzer.show_details()
        elif args.mode == 'week':
            analyzer.show_week_stats(categorize=args.categorize)
        else:  # overall
            analyzer.show_overall_stats(categorize=args.categorize)
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
