# ============================================================
#  reports.py — Cognitive Diagnostics & Spaced-Repetition Analytics Engine
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import time
import math
from typing import Dict, List, Any, Optional

CATEGORIES = [
    "Cognitive Memory",
    "Logical Reasoning",
    "Critical Thinking",
    "Creative Application"
]

CATEGORY_COLORS = {
    "Cognitive Memory":     "#4361ee",
    "Logical Reasoning":    "#23b26d",
    "Critical Thinking":    "#e63980",
    "Creative Application": "#f8961e",
}

CATEGORY_DEFINITIONS = {
    "Cognitive Memory": "Measures your ability to recall specific facts, definitions, terminology, and core concepts presented in the material.",
    "Logical Reasoning": "Assesses how effectively you identify cause-and-effect relationships, sequential steps, and deduce conclusions from arguments.",
    "Critical Thinking": "Evaluates your capacity to analyze arguments, spot assumptions, weigh evidence, and critique claims in the study notes.",
    "Creative Application": "Tests your skill at applying concepts to novel hypothetical scenarios, problem-solving, and cross-domain applications.",
}

# Detailed diagnostic feedback mapped by percentage performance (0-4 scale normalized)
CATEGORY_FEEDBACK = {
    "Cognitive Memory": {
        0: {
            "analysis": "Struggling with recalling core facts and terminology. Building a factual foundation is your primary priority.",
            "tips": [
                "Create digital or physical flashcards for key definitions and terms.",
                "Summarize each section of your notes in 2-3 bullet points immediately after reading.",
                "Review definitions using active recall rather than passive re-reading."
            ]
        },
        1: {
            "analysis": "You recall surface concepts but miss specific data points, dates, and precise terminology.",
            "tips": [
                "Highlight key definitions and formulas in your notes.",
                "Use mnemonic devices (acronyms or association chains) for lists.",
                "Schedule a quick 5-minute review 24 hours after your initial study session."
            ]
        },
        2: {
            "analysis": "Decent grasp of main ideas, but finer details and complex terminology need reinforcement.",
            "tips": [
                "Practice explaining the concepts aloud without referencing the source notes.",
                "Draw mind maps linking core terms to their secondary attributes.",
                "Self-test on definitions using the Flashcard tool."
            ]
        },
        3: {
            "analysis": "Strong recall of facts, definitions, and principles with minimal gaps.",
            "tips": [
                "Connect these solid facts to broader conceptual themes in other topics.",
                "Review periodically to maintain long-term memory retention.",
                "Formulate your own test questions to deepen mastery."
            ]
        },
        4: {
            "analysis": "Mastery level! Outstanding precision and complete accuracy in factual recall.",
            "tips": [
                "Explore advanced source literature or edge cases beyond the primary notes.",
                "Help teach or summarize this topic for fellow students."
            ]
        }
    },
    "Logical Reasoning": {
        0: {
            "analysis": "Difficulty connecting ideas, following logical progressions, and determining cause-and-effect.",
            "tips": [
                "Identify keywords indicating relationships like 'because', 'therefore', 'results in', and 'leads to'.",
                "Draw flowchart diagrams showing step-by-step progressions.",
                "Break long, complex sentences into simple premise-and-conclusion pairs."
            ]
        },
        1: {
            "analysis": "Understands simple direct arguments, but multi-step inferences or conditional logic cause confusion.",
            "tips": [
                "Ask 'What is the immediate consequence of this step?' at each paragraph.",
                "Map out the logical flow on paper before answering questions.",
                "Examine why incorrect options are logically invalid."
            ]
        },
        2: {
            "analysis": "Good logical understanding, with occasional slips on nuanced or multi-variable deductions.",
            "tips": [
                "Look for hidden assumptions in arguments.",
                "Test whether a conclusion strictly follows from the stated premise or is merely possible.",
                "Practice structured problem-solving walkthroughs."
            ]
        },
        3: {
            "analysis": "High logical competence. You readily follow structured reasoning and deduce valid conclusions.",
            "tips": [
                "Challenge yourself to anticipate the next logical step before reading it.",
                "Identify counterexamples that would challenge standard assertions."
            ]
        },
        4: {
            "analysis": "Exceptional logical deduction! You deconstruct complex arguments with analytical precision.",
            "tips": [
                "Apply formal logic structures to interdisciplinary topics.",
                "Analyze structural proofs and advanced derivations."
            ]
        }
    },
    "Critical Thinking": {
        0: {
            "analysis": "Accepting claims at face value without evaluating evidence or questioning assumptions.",
            "tips": [
                "Always ask: 'What evidence supports this claim?' and 'Is the evidence strong or weak?'",
                "Distinguish strictly between stated facts and the author's opinions/interpretations.",
                "Look for potential counterarguments or alternative interpretations."
            ]
        },
        1: {
            "analysis": "Identifies main points but finds it challenging to weigh conflicting evidence or spot biases.",
            "tips": [
                "Compare and contrast two different perspectives in the text.",
                "Identify what important information or context might be missing.",
                "Practice formulating 'What if?' counter-scenarios."
            ]
        },
        2: {
            "analysis": "Solid critical evaluation, but deeper scrutiny of subtleties and edge cases is needed.",
            "tips": [
                "Evaluate the validity and reliability of evidence cited.",
                "Assess whether real-world constraints would impact the conclusions.",
                "Discuss complex topics with peers to hear diverse viewpoints."
            ]
        },
        3: {
            "analysis": "Sharp analytical skills. You effectively question material and evaluate nuances.",
            "tips": [
                "Synthesize contrasting viewpoints into a comprehensive balanced argument.",
                "Evaluate the broader philosophical and systemic implications."
            ]
        },
        4: {
            "analysis": "Superior critical thinker! You exhibit deep analytical acumen and rigorous judgment.",
            "tips": [
                "Formulate comprehensive critiques and thesis-level arguments.",
                "Examine how paradigms in this domain have evolved over time."
            ]
        }
    },
    "Creative Application": {
        0: {
            "analysis": "Struggling to apply principles to unfamiliar scenarios or hypothetical problem statements.",
            "tips": [
                "Start by reviewing the core rules or principles explicitly.",
                "Think of 2 simple real-world examples for each theoretical concept.",
                "Work through practical case studies step-by-step."
            ]
        },
        1: {
            "analysis": "Can apply ideas to familiar standard examples, but novel or abstract scenarios present challenges.",
            "tips": [
                "Rephrase the problem in your own words before attempting a solution.",
                "Break large unfamiliar problems into familiar sub-components.",
                "Relate new scenario constraints back to known textbook examples."
            ]
        },
        2: {
            "analysis": "Competent practical application with room for greater flexibility and innovative approaches.",
            "tips": [
                "Brainstorm multiple distinct ways to solve the same problem.",
                "Analyze the pros and cons of each possible implementation.",
                "Consider edge cases and boundary conditions in application."
            ]
        },
        3: {
            "analysis": "Skillful at taking theory and creating effective solutions in new and unfamiliar domains.",
            "tips": [
                "Combine multiple distinct concepts to design innovative systems.",
                "Analyze efficiency, scalability, and optimization in your solutions."
            ]
        },
        4: {
            "analysis": "Top-tier creative problem solver! Exceptional ability to transfer knowledge across contexts.",
            "tips": [
                "Design novel problem sets or mini-projects to push boundary limits.",
                "Explore applying these principles to entirely different engineering/academic fields."
            ]
        }
    }
}


def calculate_knowledge_points(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes performance-driven mastery points, tier, and progression based on test history.
    Scoring Model:
      - Correct answer: +20 pts
      - Incorrect / skipped answer: -10 pts (underperformance deduction)
      - High accuracy bonus (>=90%): +50 bonus pts
      - Proficiency bonus (>=75%): +25 bonus pts
      - Low performance penalty (<50%): -40 penalty pts
      - Critical underperformance (<30%): -80 penalty pts
    Points dynamically increase on strong performance and decrease on poor performance.
    """
    total_correct = 0
    total_questions = 0
    total_points = 0
    
    for test in history:
        t_correct = 0
        t_total = 0
        scores = test.get("scores", {})
        if scores:
            for cat, data in scores.items():
                t_correct += data.get("score", 0)
                t_total += data.get("total", 0)
        else:
            t_correct = test.get("totalScore", 0)
            t_total = test.get("totalPossible", 0)
            
        total_correct += t_correct
        total_questions += t_total
        
        t_incorrect = max(0, t_total - t_correct)
        accuracy = (t_correct / t_total * 100.0) if t_total > 0 else 0.0
        
        test_net = (t_correct * 20) - (t_incorrect * 10)
        if accuracy >= 90.0:
            test_net += 50
        elif accuracy >= 75.0:
            test_net += 25
        elif accuracy < 30.0 and t_total > 0:
            test_net -= 80
        elif accuracy < 50.0 and t_total > 0:
            test_net -= 40
            
        total_points += test_net

    # Points are floored at 0 minimum
    points = max(0, total_points)
    
    # 6 Dynamic Knowledge Tiers based on accumulated mastery
    if points < 500:
        tier = "Novice"
        current_tier_min = 0
        next_tier_points = 500
    elif points < 1500:
        tier = "Apprentice"
        current_tier_min = 500
        next_tier_points = 1500
    elif points < 3000:
        tier = "Practitioner"
        current_tier_min = 1500
        next_tier_points = 3000
    elif points < 5000:
        tier = "Scholar"
        current_tier_min = 3000
        next_tier_points = 5000
    elif points < 7500:
        tier = "Master"
        current_tier_min = 5000
        next_tier_points = 7500
    else:
        tier = "Grandmaster"
        current_tier_min = 7500
        next_tier_points = 12000  # Cap
        
    progress_pct = 0
    if next_tier_points > current_tier_min:
        progress_pct = min(100, max(0, int(((points - current_tier_min) / (next_tier_points - current_tier_min)) * 100)))

    return {
        "points": points,
        "tier": tier,
        "nextTierPoints": next_tier_points,
        "currentTierMin": current_tier_min,
        "progressPct": progress_pct,
        "totalCorrect": total_correct,
        "totalQuestions": total_questions,
        "testsCompleted": len(history)
    }


def compute_current_test_report(
    test_id: str,
    topic: str,
    questions: List[Dict[str, Any]],
    user_answers: Dict[str, str],
    time_taken_seconds: Optional[int] = None
) -> Dict[str, Any]:
    """
    Analyzes a completed test attempt and generates a full diagnostic report.
    """
    category_stats = {
        cat: {"score": 0, "total": 0, "questions": []}
        for cat in CATEGORIES
    }
    
    total_correct = 0
    question_reviews = []
    chapter_stats = {}
    
    for q in questions:
        q_id = str(q.get("id"))
        cat = q.get("category", "Cognitive Memory")
        chap = q.get("chapterTitle") or "General Chapter"

        if cat not in category_stats:
            category_stats[cat] = {"score": 0, "total": 0, "questions": []}
        if chap not in chapter_stats:
            chapter_stats[chap] = {"score": 0, "total": 0}
            
        correct_ans = q.get("correctAnswer", "").strip()
        user_ans = user_answers.get(q_id, "").strip()
        
        is_correct = (user_ans.lower() == correct_ans.lower()) if user_ans else False
        if is_correct:
            total_correct += 1
            category_stats[cat]["score"] += 1
            chapter_stats[chap]["score"] += 1
            
        category_stats[cat]["total"] += 1
        chapter_stats[chap]["total"] += 1
        
        review_item = {
            "id": q.get("id"),
            "category": cat,
            "chapterTitle": q.get("chapterTitle", ""),
            "sourcePage": q.get("sourcePage"),
            "questionText": q.get("questionText"),
            "options": q.get("options", []),
            "userAnswer": user_ans or "Not Answered",
            "correctAnswer": correct_ans,
            "isCorrect": is_correct,
            "explanation": q.get("explanation", f"The correct answer is {correct_ans}.")
        }
        question_reviews.append(review_item)
        category_stats[cat]["questions"].append(review_item)

    total_questions = len(questions)
    percentage = round((total_correct / total_questions) * 100, 1) if total_questions > 0 else 0.0

    # Chapter breakdown
    chapter_breakdown = {}
    for chap, cdata in chapter_stats.items():
        score = cdata["score"]
        tot = cdata["total"]
        pct = round((score / tot) * 100, 1) if tot > 0 else 0.0
        chapter_breakdown[chap] = {
            "score": score,
            "total": tot,
            "percentage": pct
        }

    # Grade classification
    if percentage >= 90:
        grade = "A+ (Mastery)"
        badge_color = "#23b26d"
    elif percentage >= 80:
        grade = "A (Proficient)"
        badge_color = "#4361ee"
    elif percentage >= 70:
        grade = "B (Good)"
        badge_color = "#4895ef"
    elif percentage >= 60:
        grade = "C (Passing)"
        badge_color = "#f8961e"
    else:
        grade = "Needs Improvement"
        badge_color = "#e63980"

    # Category breakdown with personalized analysis & tips
    category_breakdown = {}
    weakest_category = None
    lowest_cat_pct = 101.0
    strongest_category = None
    highest_cat_pct = -1.0
    
    for cat, data in category_stats.items():
        score = data["score"]
        total = data["total"]
        pct = round((score / total) * 100, 1) if total > 0 else 0.0
        
        if pct < lowest_cat_pct and total > 0:
            lowest_cat_pct = pct
            weakest_category = cat
        if pct > highest_cat_pct and total > 0:
            highest_cat_pct = pct
            strongest_category = cat
            
        # Map percentage to 0-4 tier for feedback
        score_level = min(4, max(0, int(round((pct / 100.0) * 4))))
        feedback_info = CATEGORY_FEEDBACK.get(cat, {}).get(score_level, {
            "analysis": "Review core concepts in this section.",
            "tips": ["Re-read the relevant section in your notes.", "Practice more questions."]
        })
        
        category_breakdown[cat] = {
            "score": score,
            "total": total,
            "percentage": pct,
            "color": CATEGORY_COLORS.get(cat, "#4361ee"),
            "definition": CATEGORY_DEFINITIONS.get(cat, ""),
            "analysis": feedback_info["analysis"],
            "tips": feedback_info["tips"]
        }

    # Interlinking recommendation
    weak_areas = [cat for cat, d in category_breakdown.items() if d["percentage"] < 60]
    recommended_action = None
    if weak_areas:
        recommended_action = {
            "type": "schedule_plan",
            "topic": f"{topic} ({', '.join(weak_areas)})",
            "message": f"We detected lower scores in {', '.join(weak_areas)}. Would you like to schedule a focused review in your Study Planner?",
            "suggestedDurationMins": 30
        }
    else:
        recommended_action = {
            "type": "celebrate",
            "topic": topic,
            "message": "Outstanding performance across all categories! Keep up this momentum for your next topic.",
            "suggestedDurationMins": 25
        }

    # Performance-based Mastery Points Delta for this specific test
    incorrect_count = total_questions - total_correct
    points_delta = (total_correct * 20) - (incorrect_count * 10)
    if percentage >= 90.0:
        points_delta += 50
    elif percentage >= 75.0:
        points_delta += 25
    elif percentage < 30.0 and total_questions > 0:
        points_delta -= 80
    elif percentage < 50.0 and total_questions > 0:
        points_delta -= 40

    return {
        "testId": test_id,
        "topic": topic,
        "totalCorrect": total_correct,
        "totalQuestions": total_questions,
        "percentage": percentage,
        "pointsDelta": points_delta,
        "grade": grade,
        "badgeColor": badge_color,
        "timeTakenSeconds": time_taken_seconds,
        "strongestCategory": strongest_category,
        "weakestCategory": weakest_category,
        "categoryBreakdown": category_breakdown,
        "chapterBreakdown": chapter_breakdown,
        "recommendedAction": recommended_action,
        "questionReviews": question_reviews,
        "timestamp": int(time.time() * 1000)
    }


def compute_forgetting_curve(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes Ebbinghaus Forgetting Curve points based on student test history:
    Formula: R(t) = R_0 * e^(-t / S)
    """
    if not history:
        return {
            "curveData": [],
            "retentionPercent": 100,
            "topic": "No tests taken",
            "status": "Take your first test to track memory retention."
        }

    # Prefer the most recent test that had answers/score
    scored_tests = [t for t in history if t.get("totalScore", 0) > 0]
    latest = max(scored_tests if scored_tests else history, key=lambda x: x.get("timestamp", 0))
    total_score = sum(c.get("score", 0) for c in latest.get("scores", {}).values())
    total_possible = sum(c.get("total", 0) for c in latest.get("scores", {}).values())
    
    r0 = (total_score / total_possible) * 100 if (total_possible > 0 and total_score > 0) else 75.0
    
    time_since_days = max(0, ((time.time() * 1000) - latest.get("timestamp", time.time() * 1000)) / (1000 * 60 * 60 * 24))
    
    # Stability factor S increases with more tests completed
    stability_factor = 2.0 + (len(history) * 0.8)
    
    # Current estimated retention
    current_retention = round(r0 * math.exp(-time_since_days / stability_factor), 1)
    
    # Generate 7-day projected curve
    curve_points = []
    for day in range(0, 8):
        ret = round(r0 * math.exp(-day / stability_factor), 1)
        curve_points.append({
            "day": f"Day {day}",
            "retention": max(10, ret)
        })

    return {
        "currentRetention": current_retention,
        "retentionPercent": current_retention,
        "initialScore": round(r0, 1),
        "daysSinceTest": round(time_since_days, 1),
        "curveData": curve_points,
        "topic": latest.get("topic", "General Notes"),
        "stabilityFactor": round(stability_factor, 1),
        "needsReview": current_retention < 60
    }


def compute_overall_diagnostic_report(history: List[Dict[str, Any]], student_name: str = "Student") -> Dict[str, Any]:
    """
    Synthesizes all completed test attempts into a comprehensive, multi-dimensional
    overall diagnostic report across all cognitive domains, highlighting cumulative strengths,
    critical weak areas, and actionable pedagogical improvement strategies.
    """
    if not history:
        return {
            "totalTests": 0,
            "totalCorrect": 0,
            "totalQuestions": 0,
            "overallPercentage": 0.0,
            "grade": "No Tests Attempted",
            "badgeColor": "#64748b",
            "knowledgePoints": {"points": 0, "tier": "Novice", "progressPct": 0, "nextTierPoints": 500},
            "categoryBreakdown": {
                cat: {
                    "score": 0,
                    "total": 0,
                    "percentage": 0.0,
                    "status": "No Data",
                    "color": CATEGORY_COLORS.get(cat, "#4361ee"),
                    "definition": CATEGORY_DEFINITIONS.get(cat, ""),
                    "analysis": "Take your first practice test to generate overall cognitive diagnostics.",
                    "tips": ["Upload study notes and generate your first practice test."]
                } for cat in CATEGORIES
            },
            "weakestCategory": None,
            "strongestCategory": None,
            "weakCategories": [],
            "actionPlan": ["Start by generating a practice test on any topic in your library."],
            "testsPassed": 0,
            "testsFailed": 0,
            "recommendedAction": None,
            "studentName": student_name
        }

    total_correct = 0
    total_questions = 0
    tests_passed = 0
    tests_failed = 0
    topic_scores = {}

    category_stats = {
        cat: {"score": 0, "total": 0}
        for cat in CATEGORIES
    }

    for test in history:
        t_correct = test.get("totalScore", 0)
        t_possible = test.get("totalPossible", 0)
        t_pct = test.get("percentage", 0.0)
        topic = test.get("topic", "General Study")

        total_correct += t_correct
        total_questions += t_possible

        if t_pct >= 60.0:
            tests_passed += 1
        else:
            tests_failed += 1

        if topic not in topic_scores:
            topic_scores[topic] = {"correct": 0, "total": 0, "attempts": 0}
        topic_scores[topic]["correct"] += t_correct
        topic_scores[topic]["total"] += t_possible
        topic_scores[topic]["attempts"] += 1

        scores = test.get("scores", {})
        if scores:
            for cat, data in scores.items():
                if cat in category_stats:
                    category_stats[cat]["score"] += data.get("score", 0)
                    category_stats[cat]["total"] += data.get("total", 0)

    overall_percentage = round((total_correct / total_questions) * 100.0, 1) if total_questions > 0 else 0.0

    if overall_percentage >= 90.0:
        grade = "A+ (Mastery)"
        badge_color = "#23b26d"
    elif overall_percentage >= 80.0:
        grade = "A (Proficient)"
        badge_color = "#4361ee"
    elif overall_percentage >= 70.0:
        grade = "B (Good)"
        badge_color = "#4895ef"
    elif overall_percentage >= 60.0:
        grade = "C (Passing)"
        badge_color = "#f8961e"
    else:
        grade = "Needs Improvement"
        badge_color = "#e63980"

    category_breakdown = {}
    weakest_cat = None
    lowest_pct = 101.0
    strongest_cat = None
    highest_pct = -1.0
    weak_categories = []

    for cat, data in category_stats.items():
        score = data["score"]
        total = data["total"]
        pct = round((score / total) * 100.0, 1) if total > 0 else 0.0

        if pct < lowest_pct and total > 0:
            lowest_pct = pct
            weakest_cat = cat
        if pct > highest_pct and total > 0:
            highest_pct = pct
            strongest_cat = cat
        if pct < 60.0:
            weak_categories.append(cat)

        score_level = min(4, max(0, int(round((pct / 100.0) * 4)))) if total > 0 else 0
        feedback_info = CATEGORY_FEEDBACK.get(cat, {}).get(score_level, {
            "analysis": "Review foundational concepts.",
            "tips": ["Review notes using active recall.", "Take regular practice drills."]
        })

        status = "Strong Mastery" if pct >= 80.0 else "Developing" if pct >= 60.0 else "Critical Weak Area"

        category_breakdown[cat] = {
            "score": score,
            "total": total,
            "percentage": pct,
            "status": status,
            "color": CATEGORY_COLORS.get(cat, "#4361ee"),
            "definition": CATEGORY_DEFINITIONS.get(cat, ""),
            "analysis": feedback_info["analysis"],
            "tips": feedback_info["tips"]
        }

    # Identify lowest scoring topic
    lowest_topic = None
    lowest_topic_pct = 101.0
    for top, tdata in topic_scores.items():
        if tdata["total"] > 0:
            tpct = (tdata["correct"] / tdata["total"]) * 100.0
            if tpct < lowest_topic_pct:
                lowest_topic_pct = tpct
                lowest_topic = top

    # Personalized Action Plan
    action_plan = []
    if weak_categories:
        action_plan.append(f"Focus specifically on **{', '.join(weak_categories)}** using targeted active recall drills rather than passive re-reading.")
    if lowest_topic and lowest_topic_pct < 70.0:
        action_plan.append(f"Schedule a dedicated review session for **{lowest_topic}** (currently averaging {lowest_topic_pct:.1f}%).")
    action_plan.append("Use the Flashcards tool to self-test on core definitions every 48 hours to flatten your Ebbinghaus forgetting curve.")
    action_plan.append("Take a targeted remedial MCQ test every 3-4 study sessions to track your cognitive domain improvements.")

    recommended_action = None
    if weak_categories or (lowest_topic and lowest_topic_pct < 65.0):
        remedial_topic = lowest_topic or (f"Remedial: {weakest_cat}" if weakest_cat else "Core Revision")
        recommended_action = {
            "type": "schedule_plan",
            "topic": remedial_topic,
            "message": f"Your overall analytics show lower retention in {', '.join(weak_categories) if weak_categories else remedial_topic}. Would you like to schedule an AI-guided remedial review in your Study Planner?",
            "suggestedDurationMins": 35
        }
    else:
        recommended_action = {
            "type": "celebrate",
            "topic": "All Topics",
            "message": f"Outstanding cumulative mastery ({overall_percentage}%) across all {len(history)} tests! Keep reinforcing with spaced repetition.",
            "suggestedDurationMins": 25
        }

    knowledge_points = calculate_knowledge_points(history)

    return {
        "totalTests": len(history),
        "totalCorrect": total_correct,
        "totalQuestions": total_questions,
        "overallPercentage": overall_percentage,
        "grade": grade,
        "badgeColor": badge_color,
        "knowledgePoints": knowledge_points,
        "categoryBreakdown": category_breakdown,
        "weakestCategory": weakest_cat,
        "strongestCategory": strongest_cat,
        "weakCategories": weak_categories,
        "testsPassed": tests_passed,
        "testsFailed": tests_failed,
        "lowestTopic": lowest_topic,
        "lowestTopicPct": round(lowest_topic_pct, 1) if lowest_topic else None,
        "actionPlan": action_plan,
        "recommendedAction": recommended_action,
        "studentName": student_name
    }
