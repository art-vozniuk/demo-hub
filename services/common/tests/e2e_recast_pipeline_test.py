import asyncio
import argparse
import os
import sys
import time
from uuid import uuid4
import httpx
from supabase import create_client, Client

CORE_API_URL = os.getenv("CORE_API_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD")

MAX_POLL_TIME = 90
POLL_INTERVAL = 2


def parse_s3_url(url: str):
    parts = url.split("/")
    bucket = parts[-3]
    key = "/".join(parts[-2:])
    return {"bucket": bucket, "key": key}


async def run_single_test(
    client: httpx.AsyncClient,
    headers: dict,
    templates: list,
    test_num: int,
    total_tests: int,
) -> dict:
    try:
        start_time = time.time()

        if len(templates) < 2:
            return {
                "success": False,
                "error": f"Not enough templates. Found: {len(templates)}, need at least 2",
                "duration": 0,
            }

        source_template = templates[0]
        target_template = templates[1]
        source_s3 = parse_s3_url(source_template["url"])
        target_s3 = parse_s3_url(target_template["url"])

        trace_id = str(uuid4())
        pipeline_id = str(uuid4())

        queue_payload = {
            "trace_id": trace_id,
            "jobs": [
                {
                    "pipeline_id": pipeline_id,
                    "pipeline_name": "recast",
                    "input": {
                        "source_image_bucket": source_s3["bucket"],
                        "source_image_key": source_s3["key"],
                        "template_image_bucket": target_s3["bucket"],
                        "template_image_key": target_s3["key"],
                    },
                }
            ],
        }

        prefix = f"[{test_num}/{total_tests}]" if total_tests > 1 else ""
        print(f"{prefix} Queueing pipeline (trace_id={trace_id[:8]}...)...")

        queue_response = await client.post(
            f"{CORE_API_URL}/v1/pipelines/queue",
            json=queue_payload,
            headers=headers,
        )
        queue_response.raise_for_status()
        queue_data = queue_response.json()

        print(
            f"{prefix} Pipeline queued: {pipeline_id[:8]}... (queue_length={queue_data.get('queue_length', 'unknown')})"
        )

        poll_start = time.time()
        result_url = None

        while time.time() - poll_start < MAX_POLL_TIME:
            status_payload = {"pipeline_ids": [pipeline_id]}

            status_response = await client.post(
                f"{CORE_API_URL}/v1/pipelines/status",
                json=status_payload,
                headers=headers,
            )
            status_response.raise_for_status()
            status_data = status_response.json()

            if status_data["pipelines"]:
                pipeline = status_data["pipelines"][0]
                status = pipeline["status"]
                elapsed = int(time.time() - poll_start)

                if status == "COMPLETED":
                    result_url = pipeline.get("result_url")
                    print(f"{prefix} Pipeline completed in {elapsed}s")
                    break
                elif status == "FAILED":
                    error_msg = pipeline.get("message", "Unknown error")
                    return {
                        "success": False,
                        "error": f"Pipeline failed: {error_msg}",
                        "duration": time.time() - start_time,
                    }

            await asyncio.sleep(POLL_INTERVAL)
        else:
            return {
                "success": False,
                "error": f"Pipeline timed out after {MAX_POLL_TIME}s",
                "duration": time.time() - start_time,
            }

        if not result_url:
            return {
                "success": False,
                "error": "No result URL returned",
                "duration": time.time() - start_time,
            }

        download_response = await client.get(result_url)
        download_response.raise_for_status()

        image_size = len(download_response.content)
        print(f"{prefix} Downloaded result image ({image_size} bytes)")

        if image_size < 1000:
            return {
                "success": False,
                "error": f"Image seems too small ({image_size} bytes)",
                "duration": time.time() - start_time,
            }

        duration = time.time() - start_time
        return {"success": True, "duration": duration, "image_size": image_size}

    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            "duration": time.time() - start_time if "start_time" in locals() else 0,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "duration": time.time() - start_time if "start_time" in locals() else 0,
        }


async def main():
    parser = argparse.ArgumentParser(description="E2E Recast Pipeline Test")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of concurrent requests to send (default: 1)",
    )
    args = parser.parse_args()

    test_count = args.count

    if test_count > 1:
        print(
            f"Starting E2E recast pipeline load test with {test_count} concurrent requests..."
        )
    else:
        print("Starting E2E recast pipeline test...")

    if not all(
        [CORE_API_URL, SUPABASE_URL, SUPABASE_KEY, TEST_USER_EMAIL, TEST_USER_PASSWORD]
    ):
        print("ERROR: Missing required environment variables")
        sys.exit(1)

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

        print(f"Authenticating as {TEST_USER_EMAIL}...")
        auth_response = supabase.auth.sign_in_with_password(
            {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )

        access_token = auth_response.session.access_token
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        print("Authentication successful")

        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Fetching templates...")
            templates_response = await client.get(f"{CORE_API_URL}/v1/recast/templates")
            templates_response.raise_for_status()
            templates = templates_response.json()

            if len(templates) < 2:
                print(
                    f"ERROR: Not enough templates. Found: {len(templates)}, need at least 2"
                )
                sys.exit(1)

            print(f"Found {len(templates)} templates")
            print(f"Using templates: {templates[0]['name']} -> {templates[1]['name']}")
            print()

            overall_start = time.time()

            if test_count == 1:
                results = [await run_single_test(client, headers, templates, 1, 1)]
            else:
                tasks = [
                    run_single_test(client, headers, templates, i + 1, test_count)
                    for i in range(test_count)
                ]
                results = await asyncio.gather(*tasks)

            overall_duration = time.time() - overall_start

            print()
            print("=" * 60)
            print("Test Results Summary")
            print("=" * 60)

            successful = sum(1 for r in results if r["success"])
            failed = len(results) - successful

            print(f"Total requests: {len(results)}")
            print(f"Successful: {successful}")
            print(f"Failed: {failed}")
            print(f"Success rate: {successful / len(results) * 100:.1f}%")
            print(f"Total time: {overall_duration:.2f}s")

            if successful > 0:
                successful_results = [r for r in results if r["success"]]
                durations = [r["duration"] for r in successful_results]
                avg_duration = sum(durations) / len(durations)
                min_duration = min(durations)
                max_duration = max(durations)

                print(f"Average duration: {avg_duration:.2f}s")
                print(f"Min duration: {min_duration:.2f}s")
                print(f"Max duration: {max_duration:.2f}s")

            if failed > 0:
                print()
                print("Failures:")
                for i, result in enumerate(results):
                    if not result["success"]:
                        print(f"  Request {i + 1}: {result['error']}")

            print("=" * 60)

            if failed > 0:
                print("E2E test failed")
                sys.exit(1)
            else:
                print("E2E test passed successfully")

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
