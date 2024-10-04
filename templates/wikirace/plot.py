import matplotlib.pyplot as plt
import numpy as np
import json
import os
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out_dir', default='.', help='Output directory where results are saved')
    args = parser.parse_args()

    out_dir = args.out_dir

    # Load the path.json file
    path_file = os.path.join(out_dir, "path.json")
    if not os.path.exists(path_file):
        print(f"Error: {path_file} not found.")
        return

    with open(path_file, 'r', encoding='utf-8') as f:
        overall_results = json.load(f)

    # Load the final_info.json file
    final_info_file = os.path.join(out_dir, "final_info.json")
    if not os.path.exists(final_info_file):
        print(f"Error: {final_info_file} not found.")
        return

    with open(final_info_file, 'r', encoding='utf-8') as f:
        final_info = json.load(f)

    # Prepare data for plotting
    success_runs = [result for result in overall_results if result['success']]
    failure_runs = [result for result in overall_results if not result['success']]

    # Plot histogram of path lengths
    path_lengths = [result['path_length'] for result in success_runs]
    plt.figure(figsize=(10, 6))
    plt.hist(path_lengths, bins=range(1, max(path_lengths)+2), align='left', edgecolor='black')
    plt.title('Distribution of Path Lengths Among Successful Runs')
    plt.xlabel('Path Length')
    plt.ylabel('Number of Runs')
    plt.xticks(range(1, max(path_lengths)+1))
    plt.grid(axis='y', alpha=0.75)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'path_length_distribution.png'))
    plt.close()

    # Plot bar chart of time taken per run
    times = [result['time_taken'] for result in overall_results]
    labels = [f"{result['start_topic']} to {result['end_topic']}" for result in overall_results]
    x = np.arange(len(labels))

    plt.figure(figsize=(12, 6))
    plt.bar(x, times, color='skyblue', edgecolor='black')
    plt.xticks(x, labels, rotation=45, ha='right')
    plt.ylabel('Time Taken (seconds)')
    plt.title('Time Taken for Each Run')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'time_per_run.png'))
    plt.close()

    # Print final statistics
    print("Final Statistics:")
    print(f"Success Rate: {final_info['success_rate']*100:.2f}%")
    print(f"Average Path Length: {final_info['average_path_length']}")
    print(f"Average Time Spent per Run: {final_info['average_time_spent']:.2f} seconds")

if __name__ == '__main__':
    main()
