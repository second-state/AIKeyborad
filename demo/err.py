def calculate_average(numbers):
    total = 0
    for num in numbers:
        total += num

    average = total / len(numbers)
    return average

my_list = [10, 20, 30, 40, 50]
result = calculate_average(my_list)

print("平均值是:" + result)