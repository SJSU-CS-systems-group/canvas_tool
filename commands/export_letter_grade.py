from core import *

@canvas_tool.command()
@click.argument("course")
@click.argument("csv_output_file", type=click.File("w"))
def export_letter_grade(course, csv_output_file):
    ''' export course letter grade to CSV

    the "Reported Letter Grade" column must be setup in the gradebook.
    this command will pull down the letter grades from that column an print a CSV record
    with the student id and the corresponding letter grade.
    output will got to the indicated csv_output_file.
    an output file name of - will go to stdout.
    '''

    canvas = get_canvas_object()
    course = get_course(canvas, course)

    rlg_assignment = get_assignment(course, "Reported Letter Grade")
    if not rlg_assignment:
        error('the "Reported Letter Grade" assignment hasn\'t been set up')
        exit(2)

    count = 0
    csv_output_file.write("Student ID,Grade\n")
    for submission in rlg_assignment.get_submissions():
        user = course.get_user(submission.user_id)
        if user.sis_user_id:
            csv_output_file.write(f"{user.sis_user_id}, {submission.grade}\n")
            count += 1

    info(f"{count} records written to {csv_output_file.name}")

