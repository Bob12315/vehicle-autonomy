# External Action contract

`ExternalFactory(create_job)` wraps an explicitly configured job client. A job
provides `poll`, `cancel` and `close`, with RUNNING feedback and SUCCEEDED,
FAILED, CANCELLED or UNKNOWN result states. Factories define their own immutable
parameter type/schema when registering. The generic scheduler knows no ROS,
HTTP, vehicle or algorithm implementation.

NativeJob runs a cooperative local function with a cancellation Event and
feedback callback. ApiJob uses an explicitly configured job endpoint: POST
`/jobs`, GET `/jobs/ID`, POST `/jobs/ID/cancel`. Endpoints and optional tokens
are deployment configuration, not arbitrary user-supplied Action URL fields.
HTTP responses and worker lines are bounded. A lost response is UNKNOWN;
killing a local client does not prove its remote job stopped. A Continuous
provider that ends without cancellation fails rather than silently succeeding.
An unknown exit retains its resource even when no vehicle scope exists.

The included ROS example explicitly starts a separate worker via the installed
`with_ros2.sh` resource. It uses a UUID namespace, a dedicated ROS_DOMAIN_ID
and localhost discovery. The application process never imports rclpy. The
worker implements the actual ROS 2 `nav2_msgs/action/Wait` client and
`std_srvs/Trigger` service client. The acceptance server is a real local DDS
ActionServer with timing, feedback, cancel and intentional error/disconnection
behavior. It performs no robot navigation and has no vehicle connection.

Primary interface references, checked against the installed Jazzy sources:

- [rclpy Jazzy ActionClient](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/action/client.py)
- [rclpy Jazzy ActionServer](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/action/server.py)
- [Wait Action message fields](https://api.nav2.org/actions/jazzy/wait.html)

`cancel_goal_async` requests cancellation; only the actual terminal result
confirms it. A missing server before submitting a goal is FAILED with no goal
sent. Lost admission/result after submission is UNKNOWN. Action deadline first
requests cancellation; confirmed cancellation yields TIMED_OUT, while unknown
remote stop retains UNKNOWN. Trigger response loss is uncertain because it
has no Action goal-cancellation protocol.

Other ROS types or native/remote algorithms can implement the same job factory
contract. This is not evidence that Nav2 navigation, SLAM, VLM, YOLO, fusion,
Mission Graph or AI task selection is implemented. ROS namespace/domain
isolation is not DDS authentication; this example trusts its locally launched
test server and never maps its outputs directly to vehicle commands.
