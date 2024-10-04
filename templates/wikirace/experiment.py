import asyncio
import aiohttp
import json
import sys
import os
import argparse
import numpy as np
import time

BASE_URL = 'https://en.wikipedia.org/w/api.php?'

async def wiki_request(session, topic, is_source):
    """
    Sends wiki request to obtain links for a topic.
    Due to a 500 link limit, additional requests must be sent based on the
    'continue' response.
    """
    cont = None
    titles = []

    while cont != 'DONE':
        if is_source:
            body = await _get_links(session, topic, cont)
            cont_type = 'plcontinue'
        else:
            body = await _get_linkshere(session, topic, cont)
            cont_type = 'lhcontinue'

        _get_titles(body, titles, cont_type)
        try:
            cont = body['continue'][cont_type]
        except KeyError:
            cont = 'DONE'

    return titles

async def _get_links(session, topic, cont):
    """
    Helper function for single wiki request.
    """
    payload = {
        'action': 'query',
        'titles': topic,
        'prop': 'links',
        'format': 'json',
        'pllimit': '500',
    }

    if cont:
        payload['plcontinue'] = cont

    async with session.get(BASE_URL, params=payload) as resp:
        if resp.status // 100 == 2:
            return await resp.json()
        else:
            raise Exception(f"HTTP Error: {resp.status}")

async def _get_linkshere(session, topic, cont):
    """
    Helper function for single wiki request.
    """
    payload = {
        'action': 'query',
        'titles': topic,
        'prop': 'linkshere',
        'format': 'json',
        'lhlimit': '500',
    }

    if cont:
        payload['lhcontinue'] = cont

    async with session.get(BASE_URL, params=payload) as resp:
        if resp.status // 100 == 2:
            return await resp.json()
        else:
            raise Exception(f"HTTP Error: {resp.status}")

def _get_titles(body, titles, cont_type):
    """
    Adds titles from response to list.
    """
    pages = body['query']['pages']
    links = []
    link_type = 'links' if cont_type == 'plcontinue' else 'linkshere'

    for page in pages:
        if link_type in pages[page]:
            links.append(pages[page][link_type])

    for link in links:
        for sub in link:
            titles.append(sub['title'])

class WikiFetch(object):
    """
    An asynchronous queue of workers listening for tasks from the WikiGraph.
    """
    def __init__(self):
        self.to_fetch = asyncio.Queue()

    async def worker(self):
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    title_to_fetch, cb, depth, is_source = await self.to_fetch.get()
                    resp = await wiki_request(session, title_to_fetch, is_source)
                    await cb(title_to_fetch, resp, depth, is_source)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"Error fetching {title_to_fetch}: {e}")

    async def producer(self, topic, cb, depth, is_source):
        await self.to_fetch.put((topic, cb, depth, is_source))

class WikiGraph(object):
    """
    A Wikipedia page and its outlinks stored as a graph.
    """
    def __init__(self):
        self.graph = {}
        self.fetcher = WikiFetch()
        self.to_visit_start = asyncio.Queue()
        self.to_visit_end = asyncio.Queue()
        self.came_from_start = {}
        self.came_from_end = {}
        self.path_found = asyncio.Future()
        self.data = []
        self.results_dict = {}

    async def shortest_path(self, start, end):
        """
        A breadth-first search for a path between a start and end topic.
        """
        if start == end:
            print([start])
            self.save_results([start], start, end)
            return [start]

        self.came_from_start[start] = None
        self.came_from_end[end] = None

        await self.to_visit_start.put((start, 0))
        await self.to_visit_end.put((end, 0))

        bfs_tasks = [
            asyncio.create_task(self.bfs(self.to_visit_start, self.came_from_start, self.came_from_end, is_source=True)),
            asyncio.create_task(self.bfs(self.to_visit_end, self.came_from_end, self.came_from_start, is_source=False))
        ]

        await self.path_found
        path = self.path_found.result()
        if path:
            print(f"Path found between '{start}' and '{end}':")
            print(path)
            self.save_results(path, start, end)
        else:
            print(f'No path found between "{start}" and "{end}".')
            self.save_results(None, start, end)

        for task in bfs_tasks:
            task.cancel()

    async def bfs(self, to_visit, came_from, dest_cf, is_source):
        try:
            while True:
                if self.path_found.done():
                    return

                cur, depth = await to_visit.get()

                # Collect data for plotting
                self.data.append({'node': cur, 'depth': depth, 'is_source': is_source})

                # Update results_dict
                dataset = 'wikirace'
                key = f"{dataset}_{'train' if is_source else 'val'}_info"
                if key not in self.results_dict:
                    self.results_dict[key] = []
                self.results_dict[key].append({
                    'iter': depth,
                    'nodes_explored': len(came_from),
                    'current_node': cur,
                })

                if cur in dest_cf:
                    path1 = self.find_path(came_from, cur)
                    path2 = self.find_path(dest_cf, cur)

                    if is_source:
                        path1.reverse()
                        path1.pop()
                        path1.extend(path2)
                        self.path_found.set_result(path1)
                    else:
                        path2.reverse()
                        path2.pop()
                        path2.extend(path1)
                        self.path_found.set_result(path2)
                    return

                if depth == 20:
                    if not self.path_found.done():
                        self.path_found.set_result(None)
                    return

                if cur not in self.graph:
                    await self.fetcher.producer(cur, self.queue_links, depth, is_source)
                else:
                    await self.queue_links(cur, self.graph[cur], depth, is_source)
        except asyncio.CancelledError:
            return

    def find_path(self, parents, dest):
        """
        Traces path from current node to parent.
        """
        path = [dest]
        while parents[dest] is not None:
            path.append(parents[dest])
            dest = parents[dest]

        return path

    async def queue_links(self, cur, resp, depth, is_source):
        """
        Adds node's children to to_visit queue for bfs.
        """
        if self.path_found.done():
            return

        to_visit = self.to_visit_start if is_source else self.to_visit_end
        came_from = self.came_from_start if is_source else self.came_from_end

        self.graph[cur] = resp
        for link in resp:
            if link in came_from:
                continue
            came_from[link] = cur
            await to_visit.put((link, depth + 1))

    def save_results(self, path, start_topic, end_topic):
        """
        Saves the path and data to the results list.
        """
        result = {
            "start_topic": start_topic,
            "end_topic": end_topic,
            "path_length": len(path) if path else None,
            "path": path if path else [],
            "success": bool(path),
            "time_taken": time.time() - self.start_time
        }
        self.results_list.append(result)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark_file', default='benchmark_pairs.json', help='JSON file containing benchmark start and end topics')
    parser.add_argument('--out_dir', default='.', help='Output directory to save results')
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    out_dir = args.out_dir
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # Load benchmark pairs from the JSON file
    benchmark_file = args.benchmark_file
    with open(benchmark_file, 'r', encoding='utf-8') as f:
        benchmark_pairs = json.load(f)

    overall_results = []
    total_time = 0
    total_path_length = 0
    success_count = 0

    # Iterate over benchmark pairs and run the experiments
    for idx, (start_topic, end_topic) in enumerate(benchmark_pairs):
        print(f"\nRunning experiment {idx + 1}/{len(benchmark_pairs)}: '{start_topic}' to '{end_topic}'")
        graph = WikiGraph()
        graph.start_time = time.time()
        graph.results_list = []
        worker_tasks = [asyncio.create_task(graph.fetcher.worker()) for _ in range(10)]
        await graph.shortest_path(start_topic, end_topic)
        for task in worker_tasks:
            task.cancel()

        # Collect results
        result = graph.results_list[0]
        overall_results.append(result)
        total_time += result['time_taken']
        if result['success']:
            success_count += 1
            total_path_length += result['path_length']

    # Calculate statistics
    success_rate = success_count / len(benchmark_pairs)
    average_path_length = total_path_length / success_count if success_count > 0 else None
    average_time_spent = total_time / len(benchmark_pairs)

    # Save final_info.json
    final_info = {
        "success_rate": success_rate,
        "average_path_length": average_path_length,
        "average_time_spent": average_time_spent
    }
    with open(os.path.join(out_dir, "final_info.json"), 'w', encoding='utf-8') as f:
        json.dump(final_info, f, ensure_ascii=False, indent=4)

    # Save path.json
    with open(os.path.join(out_dir, "path.json"), 'w', encoding='utf-8') as f:
        json.dump(overall_results, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    asyncio.run(main())
