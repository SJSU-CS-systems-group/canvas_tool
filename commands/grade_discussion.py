from core import *

@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
@click.option('--min-words', default=5, show_default=True, help="the minimum number of valid words to get credit")
@click.option('--points-comment', default=1, show_default=True, help="number of points for posting a comment")
@click.option('--max-points', default=2, show_default=True, help="maximum number of points to give")
def grade_discussion(course_name, assignment_name, dryrun, min_words, points_comment, max_points):
    '''
    grade a discussion assignment based on participation.

    one point is added for a post and another for a reply for a total of 2.
    this tool assumes that the student must post first to reply.

    course_name - any part of an active course name. for example, 249 will match CS249.
    the course must active (it has not passed the end date) to be eligible for matching.
    only the first match will be used.

    assignment_name - any part of an assigment's name will be matched. only the first
    match will be used.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    now = datetime.datetime.now(datetime.timezone.utc)
    assignments = get_assignments(course, assignment_name)
    for assignment_data in assignments:
        info(f"grading {assignment_data['title']}")
        assignment = course.get_assignment(assignment_data['assignment_id'])
        due_at_date = assignment.due_at_date
        if due_at_date > now:
            warn(f"{assignment_data['title']} not due: skipping")
            continue
        submissions = assignment.get_submissions()
        grades = {}
        skipped = 0
        processed = 0

        # we calculate the grades and upload them in two steps since the second
        # step is slow so we want to do a progress bar. we could still do it all
        # in one pass if we could get the count. i can't find a way to do that
        # without going through the submissions
        for s in submissions:
            processed += 1
            if not hasattr(s, "discussion_entries"):
                skipped += 1
                continue

            grade = 0
            for entry in s.discussion_entries:
                entry = DiscussionEntry(None, entry)
                if entry.created_at_date > due_at_date:
                    info(
                        f"skipping discussion from {s.user_id} submitted at {entry.created_at_date} but due {due_at_date}")
                    continue
                if count_words(entry.message) > 5:
                    grade = min(grade + points_comment, max_points)

            grades[s] = grade

        if skipped == processed:
            error(f"'{assignment.name}' doesn't appear to be a discussion assignment")
            sys.exit(2)

        info(f"processed {processed}, skipped {skipped}.")

        if dryrun:
            info("would have posted:")
            for i in grades.items():
                info(f"    {i[0]} {i[1]}")
        else:
            with click.progressbar(length=len(grades), label="updating grades", show_pos=True) as bar:
                for i in grades.items():
                    i[0].edit(submission={'posted_grade': i[1]})
                    bar.update(1)
